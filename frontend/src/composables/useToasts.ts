import { ref } from 'vue'

export type ToastTone = 'success' | 'error' | 'info' | 'warning'

export interface Toast {
  id: number
  message: string
  tone: ToastTone
}

const toasts = ref<Toast[]>([])
let nextId = 1

export function useToasts() {
  function dismiss(id: number) {
    toasts.value = toasts.value.filter((toast) => toast.id !== id)
  }

  function push(message: string, tone: ToastTone = 'info', duration = 4200) {
    const id = nextId++
    toasts.value = [...toasts.value, { id, message, tone }]
    window.setTimeout(() => dismiss(id), duration)
  }

  return {
    toasts,
    push,
    dismiss,
    success: (message: string) => push(message, 'success'),
    error: (message: string) => push(message, 'error', 6000),
    info: (message: string) => push(message, 'info'),
  }
}
