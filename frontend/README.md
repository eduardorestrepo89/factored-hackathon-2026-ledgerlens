# LedgerLens frontend

The React + Vite app where LATAM Bank's card holders chat with LedgerLens. It signs them in through Cognito, streams the agent's answers from AgentCore Runtime, asks for a Yes or No before the agent blocks a card, opens a claim or hands off, and splits into a human agent's desk after a hand-off.

Project overview: [README](../README.md). Deploying the whole system: [docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md).

## Prerequisites

- **Node.js ^20.19.0 or >=22.12.0, and npm.** That is the range Vite 8 supports.
- **Python 3.11+ and the AWS CLI v2 with the `ledgerlens` profile**, to generate the app's configuration.
- **A deployed main stack** (`ledgerlens-bank-assistant`). The app reads the Cognito, runtime and feedback settings from its outputs, so it has no offline mode.

## Quick start

From the repo root:

1. Write the local configuration:

   ```bash
   AWS_PROFILE=ledgerlens python scripts/deploy-frontend.py --config-only
   ```

   This writes `frontend/public/aws-exports.json` (gitignored) from the main stack's outputs: the Cognito authority and client id, `agentRuntimeArn`, `awsRegion` and `feedbackApiUrl`. The sign-in and sign-out redirects point to `http://localhost:3000`, which the Cognito web client already allows. Nothing is built or deployed.

2. Install and start the dev server:

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

3. Vite opens http://localhost:3000. Sign in with a login that is linked to a customer ([Logins and personas](../docs/usage.md#logins-and-personas)).

Rerun step 1 when the main stack is recreated: a stale `aws-exports.json` breaks the sign-in redirect.

Authentication can't be switched off for local work. The runtime only accepts requests with a valid Cognito JWT, and the chat sends the signed-in user's access token with every message.

## What the app does

- **Sign-in** (`components/auth/`): a three.js card scene (`LensScene.tsx`) and a sign-in button. Sign-in goes through Cognito managed login with the Authorization Code grant (`react-oidc-context`).
- **Chat** (`components/chat/ChatInterface.tsx`): streams the agent's reply token by token. Tool calls show as labelled steps (`hooks/useToolRenderer.ts`, `ToolCallDisplay.tsx`). Starter suggestions fill the empty chat.
- **Yes/No cards** (`ConfirmCard.tsx`): when the agent calls `block_credit_card`, `open_claim` or `human_agent_hand_off`, the stream carries a `confirmation` event and the chat shows a card. While it is open the composer is locked and focus goes to No. Only a click on Yes runs the call; the answer goes back in the next request as `confirmations: [{ interruptId, approved }]`. A card block adds a 3-second demo biometric check after Yes; Cancel is its only way to fail.
- **Hand-off** (`HandOffTicket.tsx`, `AgentDesk.tsx`, `lib/handoff.ts`): after `human_agent_hand_off` succeeds, the chat shows a ticket with the reason, priority and related ids. After the agent's goodbye the screen splits: the customer's phone on one side, a human agent's desk on the other, with the case card, the live thread, suggested replies and a composer. The split animates with the View Transitions API where the browser has it. The desk is a demo that runs in the same browser: what you type there appears in the customer's chat, and nothing is sent to a backend.
- **Languages** (`lib/i18n.tsx`): Spanish (the default), Portuguese and English, picked in the header and saved in `localStorage`. The UI language isn't sent to the agent; the agent replies in the language the customer writes in.
- **Theme:** light or dark, from the saved choice or else the OS preference.
- **Public pages** (`public/final_presentation/`, `public/ledgerlens_pitch/`): the final presentation and the pitch video, served as static files outside sign-in at `/final_presentation` and `/ledgerlens_pitch`. Amplify serves them directly; `main.tsx` redirects to their `index.html` when the SPA gets the path instead (the dev server). The pitch video (`*.mp4`) isn't in git, so a fresh clone builds the pitch page without it.
- **Feedback** (`FeedbackDialog.tsx`, `services/feedbackService.ts`): thumbs up or down with an optional comment, posted to `<feedbackApiUrl>feedback` with the user's ID token. API Gateway checks it with a Cognito authorizer, and a Lambda stores it in DynamoDB.

## Streaming client

`lib/agentcore-client/` talks to the runtime:
- `client.ts` POSTs the message to `https://bedrock-agentcore.<region>.amazonaws.com/runtimes/<runtime ARN>/invocations` with the access token as a Bearer token and the session id in a header. The user's identity comes from the token on the server side, never from the body.
- `utils/sse.ts` reads the server-sent events.
- `parsers/strands.ts` turns the Strands events (text, tool use, tool results, confirmations, the final result) into UI events.

Event formats and the backend side: [docs/STREAMING.md](../docs/STREAMING.md).

## Deploying to Amplify

```bash
AWS_PROFILE=ledgerlens python scripts/deploy-frontend.py
```

The script regenerates `aws-exports.json` with the Amplify URL as the redirect, builds the app (`npm run build`, output `frontend/build`), uploads a zip to the stack's staging bucket and starts an Amplify deployment. The Amplify app has no Git connection, so a push doesn't deploy; only this script does. See [docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md).

## Project structure

```
frontend/
├── src/
│   ├── main.tsx              # entry: theme before first paint, LanguageProvider
│   ├── App.tsx               # router and AuthProvider
│   ├── routes/               # ChatPage, the only route
│   ├── app/context/          # GlobalContext
│   ├── components/
│   │   ├── auth/             # AuthProvider, AutoSignin, SignInScreen, LensScene
│   │   ├── chat/             # ChatInterface, messages, ConfirmCard, HandOffTicket, AgentDesk, FeedbackDialog
│   │   ├── loaders/          # LoadingSpinner
│   │   └── ui/               # shadcn components
│   ├── hooks/                # useAuth, useToolRenderer
│   ├── lib/
│   │   ├── agentcore-client/ # runtime client, SSE reader, Strands parser
│   │   ├── auth.ts           # Cognito settings: env vars, then aws-exports.json
│   │   ├── handoff.ts        # reads the hand-off from the stream
│   │   ├── i18n.tsx          # es / pt / en strings and the language context
│   │   └── utils.ts
│   ├── services/             # feedbackService
│   ├── styles/globals.css    # Tailwind and theme tokens
│   ├── test/                 # Vitest tests
│   ├── types/                # extra type declarations
│   └── vite-env.d.ts         # VITE_COGNITO_* types
├── public/                   # favicons; aws-exports.json is generated here
├── index.html
├── vite.config.ts            # port 3000, build to build/, vendor chunks
├── vitest.config.ts          # jsdom, src/test/setup.ts
├── eslint.config.mjs
├── components.json           # shadcn/ui configuration
└── package.json
```

## Environment variables

These optional `VITE_` variables override the Cognito settings from `aws-exports.json` (`lib/auth.ts`):

| Variable | Overrides |
|---|---|
| `VITE_COGNITO_USER_POOL_ID` and `VITE_COGNITO_REGION` | The authority. Both must be set. |
| `VITE_COGNITO_CLIENT_ID` | The web client id |
| `VITE_COGNITO_REDIRECT_URI` | The redirect after sign-in, and after sign-out when the next one isn't set |
| `VITE_COGNITO_POST_LOGOUT_REDIRECT_URI` | The redirect after sign-out |
| `VITE_COGNITO_RESPONSE_TYPE` | The OAuth response type (default `code`) |
| `VITE_COGNITO_SCOPE` | The scopes (default `email openid profile`) |
| `VITE_COGNITO_AUTOMATIC_SILENT_RENEW` | `true` or `false` |

Set them in a `.env` file in `frontend/` or in the shell. They cover only Cognito: the runtime ARN, the region and the feedback URL always come from `aws-exports.json`, so the file is required either way. `--config-only` already sets the localhost redirects, so local development needs none of these.

## Scripts

- `npm run dev`: the Vite dev server on port 3000.
- `npm run build`: type check (`tsc`), then the production build into `build/`.
- `npm run preview`: serve the production build locally.
- `npm test`: run the Vitest suite once.
- `npm run test:watch`: Vitest in watch mode.
- `npm run lint` / `npm run lint:fix`: ESLint on `src/`, without or with fixes.
- `npm run clean`: delete `build/`, `node_modules/` and `.vite/`. It uses `rm -rf`, so on Windows run it from Git Bash; npm's default shell there (cmd.exe) has no `rm`.

Repo-wide lint (ruff, ESLint, Prettier) runs from the root with `make lint`; see [CONTRIBUTING.md](../CONTRIBUTING.md).

## UI components and icons

The UI uses [shadcn/ui](https://ui.shadcn.com/docs/components) components on Radix UI, styled with Tailwind CSS 4, and [Lucide](https://lucide.dev/) icons. Add a component with:

```bash
npx shadcn@latest add dialog
```

`components.json` still points the Tailwind stylesheet at `src/app/globals.css`, but the real file is `src/styles/globals.css`. Check what `shadcn add` writes before you commit it.
