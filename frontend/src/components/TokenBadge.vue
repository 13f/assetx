<script setup lang="ts">
import { computed } from 'vue'
import type { ChainId } from '../types'

const props = withDefaults(
  defineProps<{
    symbol: string
    chain: ChainId
    size?: 'sm' | 'md'
  }>(),
  { size: 'md' },
)

const colors: Record<ChainId, [string, string]> = {
  ethereum: ['#8b9cf4', '#5f6fd1'],
  solana: ['#5eead4', '#0ea5e9'],
  bitcoin: ['#fbbf24', '#f97316'],
  nervos: ['#6ee7b7', '#10b981'],
  cosmos: ['#c4b5fd', '#8b5cf6'],
}

const palette = computed(() => colors[props.chain] ?? ['#94a3b8', '#64748b'])
const style = computed(() => ({
  background: `linear-gradient(145deg, ${palette.value[0]}, ${palette.value[1]})`,
}))
const label = computed(() => (props.symbol === 'USDT' || props.symbol === 'USDC' ? '$' : props.symbol.slice(0, 1)))
</script>

<template>
  <span
    class="inline-flex shrink-0 items-center justify-center rounded-full font-display font-bold text-slate-950 shadow-inner"
    :class="size === 'sm' ? 'h-7 w-7 text-[11px]' : 'h-9 w-9 text-xs'"
    :style="style"
    aria-hidden="true"
  >
    {{ label }}
  </span>
</template>
