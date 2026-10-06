"use client"

import { useState } from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"

interface FeedbackDialogProps {
  isOpen: boolean
  onClose: () => void
  onSubmit: (comment: string) => void
  feedbackType: "positive" | "negative"
}

export function FeedbackDialog({ isOpen, onClose, onSubmit, feedbackType }: FeedbackDialogProps) {
  const { t } = useI18n()
  const [comment, setComment] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleSubmit = async () => {
    setIsSubmitting(true)
    try {
      await onSubmit(comment)
      setComment("")
      onClose()
    } catch (error) {
      console.error("Error submitting feedback:", error)
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleCancel = () => {
    setComment("")
    onClose()
  }

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      handleCancel()
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {feedbackType === "positive" ? t("positiveFeedback") : t("negativeFeedback")}
          </DialogTitle>
          <DialogDescription>{t("feedbackPrompt")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <textarea
            id="feedback-comment"
            value={comment}
            onChange={e => setComment(e.target.value)}
            className="w-full px-3 py-2 border bg-background rounded-md focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent resize-none"
            rows={4}
            placeholder={t("feedbackPlaceholder")}
            maxLength={5000}
          />
          <div className="text-xs text-muted-foreground text-right">{comment.length} / 5000</div>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={handleCancel} disabled={isSubmitting}>
            {t("cancel")}
          </Button>
          <Button type="button" onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? t("sending") : t("send")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
