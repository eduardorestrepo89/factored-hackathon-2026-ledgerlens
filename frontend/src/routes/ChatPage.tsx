"use client"
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import ChatInterface from "@/components/chat/ChatInterface"
import { SignInScreen } from "@/components/auth/SignInScreen"
import { useAuth } from "@/hooks/useAuth"
import { GlobalContextProvider } from "@/app/context/GlobalContext"

export default function ChatPage() {
  const { isAuthenticated, signIn } = useAuth()

  if (!isAuthenticated) {
    return <SignInScreen onSignIn={() => signIn()} />
  }

  return (
    <GlobalContextProvider>
      <div className="relative h-screen">
        <ChatInterface />
      </div>
    </GlobalContextProvider>
  )
}
