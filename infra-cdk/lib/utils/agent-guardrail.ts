import * as cdk from "aws-cdk-lib"
import * as bedrock from "aws-cdk-lib/aws-bedrock"
import { createHash } from "crypto"
import { Construct } from "constructs"

// Shown in place of a blocked message. It is fixed text, so it covers the three
// languages the agent speaks (agent/ledgerlens/tools/system_prompt.py, STYLE).
const BLOCKED_MESSAGE = [
  "Solo puedo ayudarte con tus tarjetas de crédito: tus tarjetas, tus movimientos y los cargos que no reconozcas.",
  "Só posso ajudar com seus cartões de crédito: seus cartões, suas transações e cobranças que você não reconhece.",
  "I can only help with your credit cards: your cards, your transactions and charges you don't recognize.",
].join("\n")

// Guardrails can only deny named topics, so each area unrelated to banking is one topic.
// Banking requests the agent can't serve (loans, investments, new products) are left to
// the system prompt, which declines them and offers a person.
// Limits: definition up to 200 characters, up to 5 examples per topic.
const DENIED_TOPICS = [
  {
    name: "SoftwareAndCoding",
    definition:
      "Requests to write, review, debug, run, explain or design software, apps, websites, " +
      "scripts, queries or system architecture.",
    examples: [
      "Help me create a mobile app",
      "Review this Python code",
      "Write a SQL query that lists all customers",
      "Ayúdame a programar una página web",
      "Me ajuda a corrigir esse código",
    ],
  },
  {
    name: "GeneralKnowledgeAndSchoolwork",
    definition:
      "Questions about general knowledge, science, history, geography, math problems, " +
      "homework or essays that are not about the customer's bank cards.",
    // No translations: the topic then caught "talk to me in Portuguese", and the agent
    // must switch between its three languages. The prompt declines translating texts.
    examples: [
      "What is the capital of Australia?",
      "Solve this equation for x",
      "Write an essay about climate change",
      "¿Quién ganó el mundial de 2014?",
      "Me explica a fotossíntese para a minha prova",
    ],
  },
  {
    name: "EntertainmentAndLifestyle",
    definition:
      "Requests about recipes, travel planning, sports, movies, music, games, jokes, " +
      "poems, stories, health, fitness or relationships, not about the customer's cards or charges.",
    examples: [
      "Tell me a joke",
      "Give me a recipe for arepas",
      "Plan a weekend trip for me",
      "Escribe un poema de amor",
      "Qual é o melhor filme do ano?",
    ],
  },
  {
    name: "PoliticsReligionLegalMedical",
    definition:
      "Opinions or advice on politics, elections, religion, legal cases, or medical " +
      "diagnosis and treatment, not disputes or claims about the customer's card charges.",
    examples: [
      "Who should I vote for?",
      "Is God real?",
      "Can I sue my landlord?",
      "¿Qué medicamento tomo para la fiebre?",
      "O que você acha do presidente?",
    ],
  },
]

const CONTENT_FILTERS = [
  { type: "HATE", inputStrength: "HIGH", outputStrength: "HIGH" },
  { type: "INSULTS", inputStrength: "HIGH", outputStrength: "HIGH" },
  { type: "SEXUAL", inputStrength: "HIGH", outputStrength: "HIGH" },
  { type: "VIOLENCE", inputStrength: "HIGH", outputStrength: "HIGH" },
  // LOW on output: the agent's own replies about suspected fraud discuss misconduct.
  { type: "MISCONDUCT", inputStrength: "HIGH", outputStrength: "LOW" },
  // Bedrock only checks prompt attacks on input; output must be NONE.
  { type: "PROMPT_ATTACK", inputStrength: "HIGH", outputStrength: "NONE" },
]

export interface AgentGuardrailProps {
  readonly namePrefix: string
}

/**
 * Bedrock Guardrail for the agent's model: prompt-attack and content filters, and denied
 * topics unrelated to banking. It masks nothing (no sensitive-information, word or
 * grounding policy): card digits, amounts and merchants reach the customer unchanged.
 */
export class AgentGuardrail extends Construct {
  readonly guardrailArn: string
  readonly guardrailId: string
  readonly guardrailVersion: string
  // The Standard tier may run the check in any US region of this profile.
  readonly guardrailProfileId = "us.guardrail.v1:0"

  constructor(scope: Construct, id: string, props: AgentGuardrailProps) {
    super(scope, id)
    const stack = cdk.Stack.of(this)

    // Everything but the name and the profile ARN, which hold deploy-time tokens.
    const policy = {
      description: "Keeps the agent to credit card help and blocks prompt attacks. Masks nothing.",
      blockedInputMessaging: BLOCKED_MESSAGE,
      blockedOutputsMessaging: BLOCKED_MESSAGE,
      contentPolicyConfig: {
        filtersConfig: CONTENT_FILTERS,
        contentFiltersTierConfig: { tierName: "STANDARD" },
      },
      topicPolicyConfig: {
        topicsConfig: DENIED_TOPICS.map((topic) => ({ ...topic, type: "DENY" })),
        topicsTierConfig: { tierName: "STANDARD" },
      },
    }
    const guardrail = new bedrock.CfnGuardrail(this, "Guardrail", {
      name: `${props.namePrefix}-agent-guardrail`,
      // The Standard tier covers Spanish and Portuguese; it requires a cross-region profile.
      crossRegionConfig: {
        guardrailProfileArn: `arn:aws:bedrock:${stack.region}:${stack.account}:guardrail-profile/${this.guardrailProfileId}`,
      },
      ...policy,
    })

    // A version resource is only replaced when its own properties change, so the hash
    // of the configuration makes every change publish a new version.
    const configHash = createHash("sha256")
      .update(JSON.stringify({ policy, profile: this.guardrailProfileId }))
      .digest("hex")
      .slice(0, 12)
    const version = new bedrock.CfnGuardrailVersion(this, "Version", {
      guardrailIdentifier: guardrail.attrGuardrailId,
      description: `config ${configHash}`,
    })

    this.guardrailArn = guardrail.attrGuardrailArn
    this.guardrailId = guardrail.attrGuardrailId
    this.guardrailVersion = version.attrVersion
  }
}
