// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React from "react"
import ReactDOM from "react-dom/client"
import App from "./App"
import { LanguageProvider } from "./lib/i18n"
import "./styles/globals.css"

// Theme before the first paint: the saved choice, else the OS preference
let theme: string | null = null
try {
  theme = localStorage.getItem("theme")
} catch {
  // no storage: follow the OS
}
document.documentElement.classList.toggle(
  "dark",
  theme ? theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches
)

// The final presentation and the pitch video are public static pages (public/final_presentation,
// public/ledgerlens_pitch), outside sign-in. Amplify serves them directly; this hands over when the
// SPA gets the path instead (the dev server).
const publicPage = window.location.pathname.match(/^\/(final_presentation|ledgerlens_pitch)\/?$/)
if (publicPage) {
  window.location.replace(`/${publicPage[1]}/index.html` + window.location.hash)
} else {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <LanguageProvider>
        <App />
      </LanguageProvider>
    </React.StrictMode>
  )
}
