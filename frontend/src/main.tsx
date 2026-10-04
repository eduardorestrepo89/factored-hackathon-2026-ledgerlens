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

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <LanguageProvider>
      <App />
    </LanguageProvider>
  </React.StrictMode>
)
