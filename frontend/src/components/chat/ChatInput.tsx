"use client"

import { FormEvent, KeyboardEvent, useRef, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Send } from "lucide-react"
import { useI18n } from "@/lib/i18n"

interface ChatInputProps {
  input: string
  setInput: (input: string) => void
  handleSubmit: (e: FormEvent) => void
  isLoading: boolean
  className?: string
  placeholder?: string
}

export function ChatInput({
  input,
  setInput,
  handleSubmit,
  isLoading,
  className = "",
  placeholder,
}: ChatInputProps) {
  const { t } = useI18n()
  const textareaRef = useRef<HTMLTextAreaElement>(null)

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
    <div className={`p-4 w-full ${className}`}>
      <form
        onSubmit={handleSubmit}
        className="flex space-x-2 w-full items-end bg-card rounded-lg shadow-lg border p-3"
      >
        <Textarea
          ref={textareaRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder ?? t("placeholder")}
          disabled={isLoading}
          className="flex-1 min-h-[40px] max-h-[200px] resize-none py-2"
          rows={1}
          autoFocus
        />

        <Button type="submit" disabled={!input.trim() || isLoading} className="h-10">
          <Send className="h-4 w-4 mr-2" />
          {t("send")}
        </Button>
      </form>
    </div>
  )
}
