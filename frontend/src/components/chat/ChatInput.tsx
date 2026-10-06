"use client"

import { FormEvent, KeyboardEvent, useRef, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { ArrowUp } from "lucide-react"
import { useI18n } from "@/lib/i18n"
import { cn } from "@/lib/utils"

interface ChatInputProps {
  input: string
  setInput: (input: string) => void
  handleSubmit: (e: FormEvent) => void
  isLoading: boolean
  className?: string
  placeholder?: string
  /** Locked while something else needs an answer first (the consent prompt) */
  disabled?: boolean
}

export function ChatInput({
  input,
  setInput,
  handleSubmit,
  isLoading,
  className = "",
  placeholder,
  disabled = false,
}: ChatInputProps) {
  const { t } = useI18n()
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const locked = isLoading || disabled

  // Back to the composer when the agent finishes, on devices with a keyboard (on touch it
  // would pop the keyboard up after every reply)
  useEffect(() => {
    if (!locked && window.matchMedia?.("(pointer: fine)").matches)
      textareaRef.current?.focus({ preventScroll: true })
  }, [locked])

  // Auto-resize the textarea based on content
  useEffect(() => {
    const textarea = textareaRef.current
    if (textarea) {
      textarea.style.height = "0px"
      const scrollHeight = textarea.scrollHeight
      textarea.style.height = scrollHeight + "px"
    }
  }, [input])

  // Handle key presses for Ctrl+Enter to add new line and Enter to submit
  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter") {
      if (e.ctrlKey) {
        // Add a new line when Ctrl+Enter is pressed
        setInput(`${input}\n\n`)
        e.preventDefault()
      } else if (!e.shiftKey) {
        // Submit the form when Enter is pressed without Shift
        if (input.trim()) {
          e.preventDefault()
          handleSubmit(e as unknown as FormEvent)
        }
      }
    }
  }

  return (
    <div className={cn("w-full p-3 sm:p-4", className)}>
      <form
        onSubmit={handleSubmit}
        className="flex w-full items-end gap-2 rounded-[22px] border bg-card p-2 pl-4 shadow-[0_10px_30px_-18px_rgb(22_26_51/.35)] transition-shadow focus-within:border-ai/50 focus-within:ring-4 focus-within:ring-ai/10"
      >
        <Textarea
          ref={textareaRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder ?? t("placeholder")}
          disabled={locked}
          className="max-h-[200px] min-h-[40px] flex-1 resize-none border-0 bg-transparent px-0 py-2 text-base shadow-none focus-visible:ring-0 focus-visible:ring-offset-0 dark:bg-transparent"
          rows={1}
          autoFocus
        />

        <Button
          type="submit"
          disabled={!input.trim() || locked}
          size="icon"
          aria-label={t("send")}
          title={t("send")}
          className="h-10 w-10 rounded-full"
        >
          <ArrowUp className="h-5 w-5" />
        </Button>
      </form>
    </div>
  )
}
