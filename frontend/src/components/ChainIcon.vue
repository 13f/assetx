<script setup lang="ts">
import { computed } from 'vue'
import type { ChainId } from '../types'

const props = withDefaults(
  defineProps<{
    chain: ChainId
    accent?: string
    size?: 'sm' | 'md' | 'lg'
  }>(),
  { accent: '#6ee7b7', size: 'md' },
)

const sizeClass = computed(() => {
  if (props.size === 'sm') return 'h-7 w-7'
  if (props.size === 'lg') return 'h-12 w-12'
  return 'h-9 w-9'
})

const iconSize = computed(() => {
  if (props.size === 'sm') return 14
  if (props.size === 'lg') return 24
  return 18
})

const style = computed(() => ({
  color: props.accent,
  backgroundColor: `${props.accent}16`,
  borderColor: `${props.accent}33`,
}))
</script>

<template>
  <span
    class="inline-flex shrink-0 items-center justify-center rounded-xl border"
    :class="sizeClass"
    :style="style"
    aria-hidden="true"
  >
    <svg
      v-if="chain === 'ethereum'"
      :width="iconSize"
      :height="iconSize"
      viewBox="0 0 24 24"
      fill="none"
    >
      <path d="M12 2 5.5 12.2 12 16l6.5-3.8L12 2Z" fill="currentColor" opacity=".95" />
      <path d="M5.5 13.7 12 22l6.5-8.3L12 17.5l-6.5-3.8Z" fill="currentColor" opacity=".6" />
    </svg>
    <svg
      v-else-if="chain === 'solana'"
      :width="iconSize"
      :height="iconSize"
      viewBox="0 0 24 24"
      fill="none"
    >
      <path d="M6.2 7h12.4l-2-2H4.2l2 2Zm-2 6h12.4l2-2H6.6l-2.4 2Zm2 6h12.4l2-2H4.2l2 2Z" fill="currentColor" />
    </svg>
    <span v-else-if="chain === 'bitcoin'" class="font-display font-bold" :style="{ fontSize: `${iconSize}px` }">₿</span>
    <svg
      v-else-if="chain === 'nervos'"
      :width="iconSize"
      :height="iconSize"
      viewBox="0 0 24 24"
      fill="none"
    >
      <path d="m12 2 8.7 5v10L12 22l-8.7-5V7L12 2Z" stroke="currentColor" stroke-width="1.6" />
      <path d="M8.5 16V8l7 8V8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
    <svg
      v-else
      :width="iconSize"
      :height="iconSize"
      viewBox="0 0 24 24"
      fill="none"
    >
      <ellipse cx="12" cy="12" rx="10" ry="4.2" stroke="currentColor" stroke-width="1.5" />
      <ellipse cx="12" cy="12" rx="10" ry="4.2" transform="rotate(60 12 12)" stroke="currentColor" stroke-width="1.5" />
      <ellipse cx="12" cy="12" rx="10" ry="4.2" transform="rotate(120 12 12)" stroke="currentColor" stroke-width="1.5" />
      <circle cx="12" cy="12" r="2" fill="currentColor" />
    </svg>
  </span>
</template>
