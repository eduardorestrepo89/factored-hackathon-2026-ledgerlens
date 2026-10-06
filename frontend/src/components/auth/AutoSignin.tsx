"use client"

import { ReactNode, useEffect, useState, PropsWithChildren } from "react"
import { useAuth } from "react-oidc-context"
import { SignInScreen, Splash } from "./SignInScreen"

function AutoSigninContent({ children }: PropsWithChildren) {
  const auth = useAuth()

  if (auth.isLoading) {
    return <Splash />
  }

  if (!auth.isAuthenticated) {
    return <SignInScreen onSignIn={() => auth.signinRedirect()} />
  }

  return <>{children}</>
}

export function AutoSignin({ children }: { children: ReactNode }) {
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
  }, [])

  if (!mounted) {
    return null
  }

  return <AutoSigninContent>{children}</AutoSigninContent>
}
