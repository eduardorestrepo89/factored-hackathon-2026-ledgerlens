import { createContext, useContext, useState, type PropsWithChildren } from "react"

export type Lang = "es" | "pt" | "en"

export const LANGS: { code: Lang; label: string }[] = [
  { code: "es", label: "Español" },
  { code: "pt", label: "Português" },
  { code: "en", label: "English" },
]

const es = {
  newChat: "Nueva conversación",
  person: "Persona",
  personLaura: "Persona · Laura",
  connecting: "conectando",
  logout: "Cerrar sesión",
  logoutTitle: "¿Cerrar sesión?",
  logoutBody: "Tendrás que iniciar sesión de nuevo para entrar a tu cuenta.",
  cancel: "Cancelar",
  confirm: "Confirmar",
  language: "Idioma",
  darkMode: "Modo oscuro",
  lightMode: "Modo claro",
  placeholder: "Escribe un mensaje…",
  send: "Enviar",
  greeting: "Hola, soy LedgerLens",
  greetingBody: "Pregúntame por tus tarjetas, tus compras o un cargo que no reconozcas.",
  connectingToPerson: "Conectando con una persona…",
  emptyThread: "Empieza una conversación",
  lauraJoined: "Laura se unió a la conversación · {time}",
  lauraTag: "Laura · Persona",
  typing: "Escribiendo…",
  responseFailed: "No se pudo obtener respuesta: {error}",
  agentError: "Lo siento, tuve un problema procesando tu solicitud. Intenta de nuevo.",
  feedbackFailed: "No se pudo enviar tu opinión: {error}",
  goodResponse: "Buena respuesta",
  badResponse: "Mala respuesta",
  feedbackThanks: "¡Gracias por tu opinión!",
  positiveFeedback: "Opinión positiva",
  negativeFeedback: "Opinión negativa",
  feedbackPrompt: "Cuéntanos más sobre tu experiencia (opcional)",
  feedbackPlaceholder: "Comparte lo que piensas…",
  sending: "Enviando…",
  customerApp: "Cliente · App",
  inQueue: "En cola · {queue}",
  priorityHigh: "ALTA",
  priorityNormal: "Normal",
  handingOff: "Enviando a una persona…",
  caseId: "Caso {id}",
  sentToPerson: "Enviado a una persona",
  desk: "Escritorio del agente",
  deskTitle: "Escritorio del agente · Laura",
  lauraRole: "Fraudes y servicio · Mesa de personas",
  inConversation: "En conversación",
  connectingDesk: "Conectando…",
  newBadge: "Nuevo",
  queueLine: "Cola: {queue} · {reason}",
  customer: "Cliente",
  queuedSince: "En cola desde",
  assistantSummary: "Resumen del asistente",
  relatedIds: "IDs relacionados",
  alreadyTold: "Lo que ya se le dijo",
  customerThread: "Conversación del cliente",
  liveMirror: "Reflejada en vivo",
  suggestedReplies: "Respuestas sugeridas",
  use: "Usar",
  writeAsLaura: "Escribe como Laura…",
  lauraMessage: "Mensaje de Laura",
  firstMessageHint: "Tu primer mensaje le avisa al cliente que te uniste.",
  // The ticket shows these to the customer, so they never claim the bank confirmed fraud
  "reason.FRAUD_CONFIRMED": "Cargo no reconocido",
  "reason.CUSTOMER_REQUEST": "Pidió hablar con una persona",
  "reason.UNRESOLVED": "El asistente no pudo resolverlo",
  "reason.OUT_OF_SCOPE": "Fuera del alcance del asistente",
  queueFraud: "Fraudes",
  queueGeneral: "Servicio general",
  helloNamed: "Hola {name}, soy Laura, de {queue}.",
  hello: "Hola, soy Laura, de {queue}.",
  haveCase: "Ya tengo tu caso {id} y todo lo que hablaste con el asistente, así que no necesitas repetir nada.",
  "next.FRAUD_CONFIRMED": "Voy a revisar si hubo otros intentos con tus tarjetas y te cuento por aquí mismo.",
  "next.CUSTOMER_REQUEST": "Cuéntame en qué te puedo ayudar y lo revisamos juntos.",
  "next.UNRESOLVED": "Voy a revisar tu caso con más detalle y te confirmo por aquí mismo.",
  "next.OUT_OF_SCOPE": "Esa solicitud la reviso yo. Dame un momento para validar tus datos.",
}

export type Key = keyof typeof es

const pt: Record<Key, string> = {
  newChat: "Nova conversa",
  person: "Pessoa",
  personLaura: "Pessoa · Laura",
  connecting: "conectando",
  logout: "Sair",
  logoutTitle: "Sair da conta?",
  logoutBody: "Você precisará entrar de novo para acessar sua conta.",
  cancel: "Cancelar",
  confirm: "Confirmar",
  language: "Idioma",
  darkMode: "Modo escuro",
  lightMode: "Modo claro",
  placeholder: "Escreva uma mensagem…",
  send: "Enviar",
  greeting: "Olá, sou o LedgerLens",
  greetingBody: "Pergunte sobre seus cartões, suas compras ou uma cobrança que você não reconhece.",
  connectingToPerson: "Conectando com uma pessoa…",
  emptyThread: "Comece uma conversa",
  lauraJoined: "Laura entrou na conversa · {time}",
  lauraTag: "Laura · Pessoa",
  typing: "Digitando…",
  responseFailed: "Não foi possível obter resposta: {error}",
  agentError: "Desculpe, tive um problema ao processar sua solicitação. Tente novamente.",
  feedbackFailed: "Não foi possível enviar sua avaliação: {error}",
  goodResponse: "Boa resposta",
  badResponse: "Resposta ruim",
  feedbackThanks: "Obrigado pela sua avaliação!",
  positiveFeedback: "Avaliação positiva",
  negativeFeedback: "Avaliação negativa",
  feedbackPrompt: "Conte mais sobre sua experiência (opcional)",
  feedbackPlaceholder: "Compartilhe sua opinião…",
  sending: "Enviando…",
  customerApp: "Cliente · App",
  inQueue: "Na fila · {queue}",
  priorityHigh: "ALTA",
  priorityNormal: "Normal",
  handingOff: "Encaminhando para uma pessoa…",
  caseId: "Caso {id}",
  sentToPerson: "Encaminhado para uma pessoa",
  desk: "Mesa do atendente",
  deskTitle: "Mesa do atendente · Laura",
  lauraRole: "Fraudes e atendimento · Equipe humana",
  inConversation: "Em conversa",
  connectingDesk: "Conectando…",
  newBadge: "Novo",
  queueLine: "Fila: {queue} · {reason}",
  customer: "Cliente",
  queuedSince: "Na fila desde",
  assistantSummary: "Resumo do assistente",
  relatedIds: "IDs relacionados",
  alreadyTold: "O que já foi dito ao cliente",
  customerThread: "Conversa do cliente",
  liveMirror: "Espelhada ao vivo",
  suggestedReplies: "Respostas sugeridas",
  use: "Usar",
  writeAsLaura: "Escreva como Laura…",
  lauraMessage: "Mensagem da Laura",
  firstMessageHint: "Sua primeira mensagem avisa ao cliente que você entrou.",
  "reason.FRAUD_CONFIRMED": "Cobrança não reconhecida",
  "reason.CUSTOMER_REQUEST": "Pediu para falar com uma pessoa",
  "reason.UNRESOLVED": "O assistente não conseguiu resolver",
  "reason.OUT_OF_SCOPE": "Fora do escopo do assistente",
  queueFraud: "Fraudes",
  queueGeneral: "Atendimento geral",
  helloNamed: "Olá {name}, sou a Laura, de {queue}.",
  hello: "Olá, sou a Laura, de {queue}.",
  haveCase: "Já tenho seu caso {id} e tudo o que você conversou com o assistente, então não precisa repetir nada.",
  "next.FRAUD_CONFIRMED": "Vou verificar se houve outras tentativas com seus cartões e te conto por aqui mesmo.",
  "next.CUSTOMER_REQUEST": "Me conte como posso ajudar e vamos ver isso juntos.",
  "next.UNRESOLVED": "Vou analisar seu caso com mais detalhe e te confirmo por aqui mesmo.",
  "next.OUT_OF_SCOPE": "Essa solicitação fica comigo. Me dê um momento para validar seus dados.",
}

const en: Record<Key, string> = {
  newChat: "New conversation",
  person: "Person",
  personLaura: "Person · Laura",
  connecting: "connecting",
  logout: "Log out",
  logoutTitle: "Log out?",
  logoutBody: "You will need to sign in again to access your account.",
  cancel: "Cancel",
  confirm: "Confirm",
  language: "Language",
  darkMode: "Dark mode",
  lightMode: "Light mode",
  placeholder: "Type a message…",
  send: "Send",
  greeting: "Hi, I'm LedgerLens",
  greetingBody: "Ask me about your cards, your purchases or a charge you don't recognize.",
  connectingToPerson: "Connecting you with a person…",
  emptyThread: "Start a conversation",
  lauraJoined: "Laura joined the conversation · {time}",
  lauraTag: "Laura · Person",
  typing: "Typing…",
  responseFailed: "Couldn't get a response: {error}",
  agentError: "Sorry, I ran into a problem processing your request. Please try again.",
  feedbackFailed: "Couldn't send your feedback: {error}",
  goodResponse: "Good response",
  badResponse: "Bad response",
  feedbackThanks: "Thanks for your feedback!",
  positiveFeedback: "Positive feedback",
  negativeFeedback: "Negative feedback",
  feedbackPrompt: "Tell us more about your experience (optional)",
  feedbackPlaceholder: "Share your thoughts…",
  sending: "Sending…",
  customerApp: "Customer · App",
  inQueue: "In queue · {queue}",
  priorityHigh: "HIGH",
  priorityNormal: "Normal",
  handingOff: "Handing off to a person…",
  caseId: "Case {id}",
  sentToPerson: "Sent to a person",
  desk: "Agent desk",
  deskTitle: "Agent desk · Laura",
  lauraRole: "Fraud & service · Human desk",
  inConversation: "In conversation",
  connectingDesk: "Connecting…",
  newBadge: "New",
  queueLine: "Queue: {queue} · {reason}",
  customer: "Customer",
  queuedSince: "Queued since",
  assistantSummary: "Assistant summary",
  relatedIds: "Related IDs",
  alreadyTold: "What the customer was told",
  customerThread: "Customer conversation",
  liveMirror: "Mirrored live",
  suggestedReplies: "Suggested replies",
  use: "Use",
  writeAsLaura: "Write as Laura…",
  lauraMessage: "Laura's message",
  firstMessageHint: "Your first message lets the customer know you joined.",
  "reason.FRAUD_CONFIRMED": "Unrecognized charge",
  "reason.CUSTOMER_REQUEST": "Asked to talk to a person",
  "reason.UNRESOLVED": "The assistant couldn't resolve it",
  "reason.OUT_OF_SCOPE": "Outside the assistant's scope",
  queueFraud: "Fraud",
  queueGeneral: "General service",
  helloNamed: "Hi {name}, I'm Laura from {queue}.",
  hello: "Hi, I'm Laura from {queue}.",
  haveCase: "I already have your case {id} and everything you discussed with the assistant, so you don't need to repeat anything.",
  "next.FRAUD_CONFIRMED": "I'll check whether there were other attempts on your cards and update you right here.",
  "next.CUSTOMER_REQUEST": "Tell me how I can help and we'll sort it out together.",
  "next.UNRESOLVED": "I'll look into your case in more detail and confirm right here.",
  "next.OUT_OF_SCOPE": "I'll handle that request myself. Give me a moment to verify your details.",
}

const DICT: Record<Lang, Record<Key, string>> = { es, pt, en }

export const hasKey = (key: string): key is Key => key in es

/** The string for `key` in `lang`, with every {var} filled in. */
export const translate = (lang: Lang, key: Key, vars: Record<string, string> = {}): string =>
  DICT[lang][key].replace(/\{(\w+)\}/g, (_, name: string) => vars[name] ?? `{${name}}`)

// localStorage can throw (private windows, blocked site data): fall back to Spanish
function savedLang(): Lang {
  try {
    const saved = localStorage.getItem("lang")
    if (saved === "es" || saved === "pt" || saved === "en") return saved
  } catch {
    // no storage: default below
  }
  return "es"
}

interface LangContextType {
  lang: Lang
  setLang: (lang: Lang) => void
}

// The default lets components render in Spanish without a provider (tests, isolated renders)
const LangContext = createContext<LangContextType>({ lang: "es", setLang: () => {} })

export function LanguageProvider({ children }: PropsWithChildren) {
  const [lang, setLangState] = useState<Lang>(() => {
    const initial = savedLang()
    document.documentElement.lang = initial
    return initial
  })
  const setLang = (next: Lang) => {
    try {
      localStorage.setItem("lang", next)
    } catch {
      // the choice still applies for this visit
    }
    document.documentElement.lang = next
    setLangState(next)
  }
  return <LangContext.Provider value={{ lang, setLang }}>{children}</LangContext.Provider>
}

export function useI18n() {
  const { lang, setLang } = useContext(LangContext)
  return { lang, setLang, t: (key: Key, vars?: Record<string, string>) => translate(lang, key, vars) }
}
