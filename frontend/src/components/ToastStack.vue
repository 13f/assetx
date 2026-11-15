<script setup lang="ts">
import { useToasts } from '../composables/useToasts'
import type { ToastTone } from '../composables/useToasts'

const { toasts, dismiss } = useToasts()

const toneClass: Record<ToastTone, string> = {
  success: 'alert-success',
  error: 'alert-error',
  warning: 'alert-warning',
  info: 'alert-info',
}
</script>

<template>
  <div class="toast toast-end toast-bottom z-[80] w-full max-w-sm">
    <TransitionGroup name="toast">
      <div
        v-for="toast in toasts"
        :key="toast.id"
        class="alert pointer-events-auto border border-white/10 shadow-xl backdrop-blur"
        :class="toneClass[toast.tone]"
      >
        <span class="text-sm font-medium">{{ toast.message }}</span>
        <button class="btn btn-ghost btn-xs" type="button" @click="dismiss(toast.id)">✕</button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition: all 180ms ease;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
