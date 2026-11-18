<script setup lang="ts">
import { computed } from 'vue'
import type { Account, ChainMeta } from '../types'
import { formatUsd, timeAgo } from '../utils/format'
import ChainIcon from './ChainIcon.vue'

const props = defineProps<{
  chain: ChainMeta
  totalUsd: number
  share: number
  accountCount: number
  lastSyncedAt: string | null
  status: Account['total_status']
  active: boolean
}>()

const emit = defineEmits<{
  toggle: [chain: ChainMeta]
}>()

const hasAccounts = computed(() => props.accountCount > 0)
const shareLabel = computed(() => {
  if (!hasAccounts.value || props.share <= 0) return '0%'
  if (props.share < 1) return '<1%'
  if (props.share >= 99.95) return '100%'
  return `${props.share.toFixed(1)}%`
})
const barWidth = computed(() => {
  if (props.share <= 0) return 0
  return Math.min(100, Math.max(props.share, 2))
})
const statusDot = computed(() => {
  if (props.status === 'partial') return 'bg-warning'
  if (props.status === 'stale') return 'bg-base-content/25'
  return 'bg-success'
})
const statusTitle = computed(() => {
  if (props.status === 'partial') return 'Some assets on this chain could not be priced'
  if (props.status === 'stale') return 'Some accounts on this chain have not been synced'
  return 'All accounts on this chain are synced'
})
const hint = computed(() => {
  if (!hasAccounts.value) return `No ${props.chain.name} accounts yet`
  return props.active ? 'Show all chains' : `Show only ${props.chain.name} accounts`
})

function toggle() {
  if (hasAccounts.value) emit('toggle', props.chain)
}
</script>

<template>
  <button
    type="button"
    class="group relative flex h-full flex-col overflow-hidden rounded-[1.2rem] border p-3.5 text-left transition duration-300 sm:p-4"
    :class="[
      active
        ? 'border-primary/40 bg-primary/[0.07] shadow-lg shadow-primary/5'
        : 'border-base-content/10 bg-base-200/50 backdrop-blur',
      hasAccounts
        ? 'hover:-translate-y-0.5 hover:border-base-content/20 hover:bg-base-200/70 hover:shadow-xl hover:shadow-black/20'
        : 'cursor-default opacity-60',
    ]"
    :disabled="!hasAccounts"
    :aria-pressed="hasAccounts ? active : undefined"
    :title="hint"
    @click="toggle"
  >
    <span
      class="pointer-events-none absolute inset-x-0 top-0 h-px opacity-50 transition group-hover:opacity-100"
      :style="{ background: `linear-gradient(90deg, transparent, ${chain.accent}, transparent)` }"
    />

    <span class="flex items-center gap-2.5">
      <ChainIcon :chain="chain.id" :accent="chain.accent" size="sm" />
      <span class="min-w-0 flex-1">
        <span class="block truncate font-display text-[13px] font-semibold leading-tight tracking-wide">{{ chain.name }}</span>
        <span class="mt-0.5 block text-[9px] font-medium uppercase tracking-[0.16em] text-base-content/30">{{ chain.native_symbol }}</span>
      </span>
      <span class="shrink-0 text-[10px] font-medium tabular-nums text-base-content/40">{{ shareLabel }}</span>
    </span>

    <span class="mt-3 block">
      <span class="block font-display text-[1.1rem] font-semibold leading-none tracking-tight tabular-nums sm:text-[1.2rem]" :class="{ 'text-base-content/35': !hasAccounts }">
        {{ formatUsd(totalUsd) }}
      </span>
      <span class="mt-3 flex h-1 overflow-hidden rounded-full bg-base-content/[0.08]">
        <span class="h-full rounded-full transition-[width] duration-500" :style="{ width: `${barWidth}%`, backgroundColor: chain.accent }" />
      </span>
    </span>

    <span class="mt-auto flex items-center justify-between gap-2 pt-3 text-[10px]">
      <span class="flex min-w-0 items-center gap-1.5 text-base-content/35">
        <span v-if="hasAccounts" class="inline-flex h-1.5 w-1.5 shrink-0 rounded-full" :class="statusDot" :title="statusTitle" />
        <span class="truncate">{{ hasAccounts ? `${accountCount} account${accountCount === 1 ? '' : 's'}` : 'No accounts' }}</span>
      </span>
      <span v-if="hasAccounts" class="shrink-0 text-base-content/30">{{ lastSyncedAt ? timeAgo(lastSyncedAt) : 'Not synced' }}</span>
      <span v-else class="shrink-0 text-base-content/25">—</span>
    </span>
  </button>
</template>
