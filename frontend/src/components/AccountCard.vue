<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Account, ChainMeta } from '../types'
import { copyText, formatAmount, formatPrice, formatUsd, shortAddress, timeAgo } from '../utils/format'
import ChainIcon from './ChainIcon.vue'
import TokenBadge from './TokenBadge.vue'

const props = defineProps<{
  account: Account
  chain?: ChainMeta
}>()

const emit = defineEmits<{
  refresh: [account: Account]
  edit: [account: Account]
  delete: [account: Account]
  details: [account: Account]
}>()

const copied = ref(false)
const busy = computed(() => props.account.refresh?.status === 'queued' || props.account.refresh?.status === 'running')
const refreshLabel = computed(() => {
  if (props.account.refresh?.status === 'running') return 'Refreshing…'
  if (props.account.refresh?.status === 'queued') return 'Queued'
  return 'Refresh'
})
const visibleTags = computed(() => props.account.tags.slice(0, 3))
const extraTags = computed(() => Math.max(0, props.account.tags.length - visibleTags.value.length))
const hasWarning = computed(() => Boolean(props.account.last_refresh_warning || props.account.last_refresh_error))
const unpricedCount = computed(
  () => props.account.unpriced_token_count + props.account.unpriced_position_count,
)
const positionTotal = computed(() => {
  const values = props.account.positions
    .map((position) => position.value_usd)
    .filter((value): value is string => value !== null)
  if (!values.length) return '—'
  return formatUsd(values.reduce((sum, value) => sum + Number(value), 0))
})
const positionSubtitle = computed(() => {
  const positions = props.account.positions
  if (!positions.length) return ''
  const outOfRange = positions.filter((position) => !position.in_range).length
  const collection = positions[0]?.collection ?? 'Liquidity'
  const suffix = outOfRange ? `${outOfRange} out of range` : 'in range'
  return `${collection} · ${suffix}`
})

function closeMenu() {
  const active = document.activeElement
  if (active instanceof HTMLElement) active.blur()
}

function openDetails() {
  closeMenu()
  emit('details', props.account)
}

function editAccount() {
  closeMenu()
  emit('edit', props.account)
}

function removeAccount() {
  closeMenu()
  emit('delete', props.account)
}

async function copyAddress() {
  if (await copyText(props.account.address)) {
    copied.value = true
    window.setTimeout(() => (copied.value = false), 1400)
  }
}

function openExplorer() {
  if (!props.chain) return
  closeMenu()
  window.open(props.chain.explorer_url.replace('{address}', props.account.address), '_blank', 'noopener')
}
</script>

<template>
  <article
    class="group relative flex h-full flex-col overflow-hidden rounded-[1.4rem] border border-base-content/10 bg-base-200/55 backdrop-blur transition duration-300 hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-2xl hover:shadow-black/20"
    :style="{ '--chain-accent': account.accent }"
  >
    <div class="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-primary/50 to-transparent opacity-0 transition group-hover:opacity-100" />
    <div class="flex items-start justify-between gap-3 px-5 pt-5">
      <div class="flex min-w-0 items-center gap-3">
        <ChainIcon :chain="account.chain" :accent="account.accent" />
        <div class="min-w-0">
          <div class="flex items-center gap-2">
            <h3 class="font-display text-sm font-semibold tracking-wide">{{ account.chain_name }}</h3>
            <span
              class="inline-flex h-1.5 w-1.5 rounded-full"
              :class="{
                'bg-success': account.total_status === 'complete',
                'bg-warning': account.total_status === 'partial',
                'bg-base-content/25': account.total_status === 'stale',
              }"
              :title="account.total_status"
            />
          </div>
          <button
            type="button"
            class="mt-0.5 flex items-center gap-1.5 font-mono text-xs text-base-content/45 transition hover:text-base-content/80"
            :title="account.address"
            @click="copyAddress"
          >
            {{ shortAddress(account.address, 8, 6) }}
            <span v-if="copied" class="text-[10px] text-success">copied</span>
            <svg v-else width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="11" height="11" rx="2" />
              <path d="M5 15V5a2 2 0 0 1 2-2h10" />
            </svg>
          </button>
        </div>
      </div>

      <div class="dropdown dropdown-end">
        <button tabindex="0" class="btn btn-ghost btn-sm btn-circle text-base-content/45" aria-label="Account actions">⋯</button>
        <ul tabindex="0" class="dropdown-content menu z-20 mt-1 w-44 rounded-box border border-base-content/10 bg-base-200 p-1.5 text-sm shadow-2xl">
          <li><button type="button" @click="openDetails">View assets</button></li>
          <li><button type="button" @click="editAccount">Edit tags</button></li>
          <li><button type="button" @click="openExplorer">Open explorer ↗</button></li>
          <li><button type="button" class="text-error" @click="removeAccount">Remove address</button></li>
        </ul>
      </div>
    </div>

    <div class="px-5 pt-5">
      <p class="text-[11px] font-medium uppercase tracking-[0.14em] text-base-content/35">Total balance</p>
      <div class="mt-1 flex items-end gap-2">
        <p class="font-display text-[1.65rem] font-semibold leading-none tracking-tight">
          {{ formatUsd(account.total_usd) }}
        </p>
        <span
          v-if="account.total_status === 'partial'"
          class="badge badge-warning badge-soft badge-xs mb-0.5"
          :title="`${unpricedCount} asset(s) could not be priced`"
        >
          partial
        </span>
        <span v-else-if="account.total_status === 'stale'" class="badge badge-ghost badge-xs mb-0.5">not synced</span>
      </div>
    </div>

    <div class="mt-4 flex-1 px-3">
      <div v-if="account.tokens.length" class="space-y-0.5">
        <div
          v-for="token in account.tokens"
          :key="token.network_id"
          class="flex items-center justify-between gap-3 rounded-xl px-2 py-2 transition hover:bg-base-content/[0.035]"
        >
          <div class="flex min-w-0 items-center gap-2.5">
            <TokenBadge :symbol="token.symbol" :chain="account.chain" size="sm" />
            <div class="min-w-0">
              <div class="flex items-center gap-1.5">
                <span class="truncate text-sm font-semibold tracking-wide">{{ token.symbol }}</span>
                <span v-if="token.is_native" class="badge badge-ghost badge-xs px-1.5 text-[9px] uppercase">native</span>
              </div>
              <p class="truncate text-[11px] text-base-content/35">
                {{ formatAmount(token.balance) }}
                <span v-if="!token.is_native" class="text-base-content/25">· {{ token.name }}</span>
              </p>
            </div>
          </div>
          <div class="shrink-0 text-right">
            <p class="text-sm font-medium tabular-nums">{{ formatUsd(token.value_usd) }}</p>
            <p v-if="token.price_usd" class="text-[10px] tabular-nums text-base-content/30">@ {{ formatPrice(token.price_usd) }}</p>
            <p v-else class="text-[10px] text-warning/70">no price</p>
          </div>
        </div>
      </div>
      <div v-else class="flex h-full min-h-24 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-base-content/10 text-center">
        <span class="text-xl opacity-30">◌</span>
        <p class="text-xs text-base-content/40">No balances yet</p>
        <p class="text-[11px] text-base-content/25">Run a refresh to fetch this address.</p>
      </div>

      <button
        v-if="account.position_count > 0"
        type="button"
        class="mt-2 flex w-full items-center justify-between gap-3 rounded-xl border border-primary/15 bg-primary/[0.045] px-2.5 py-2 text-left transition hover:border-primary/30 hover:bg-primary/[0.08]"
        @click="emit('details', account)"
      >
        <span class="flex min-w-0 items-center gap-2.5">
          <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-primary/30 bg-primary/10 text-[10px] font-bold text-primary">LP</span>
          <span class="min-w-0">
            <span class="block truncate text-[12px] font-semibold tracking-wide">
              {{ account.position_count }} {{ account.position_count === 1 ? 'position' : 'positions' }}
            </span>
            <span class="block truncate text-[10px] text-base-content/35">{{ positionSubtitle }}</span>
          </span>
        </span>
        <span class="shrink-0 text-right">
          <span class="block text-xs font-medium tabular-nums">{{ positionTotal }}</span>
          <span v-if="account.unpriced_position_count" class="block text-[10px] text-warning/70">no price</span>
          <span v-else class="block text-[10px] text-base-content/25">LP NFT</span>
        </span>
      </button>

      <button
        v-if="account.hidden_token_count > 0"
        type="button"
        class="mt-1 w-full rounded-lg py-1.5 text-[11px] font-medium text-base-content/40 transition hover:bg-base-content/5 hover:text-primary"
        @click="emit('details', account)"
      >
        + {{ account.hidden_token_count }} more asset{{ account.hidden_token_count === 1 ? '' : 's' }}
      </button>
    </div>

    <div class="mt-3 flex items-center justify-between gap-2 border-t border-base-content/[0.07] px-5 py-3">
      <div class="flex min-w-0 items-center gap-2">
        <div class="flex flex-wrap gap-1">
          <span v-for="tag in visibleTags" :key="tag" class="badge badge-ghost badge-sm text-[10px] text-base-content/50">
            #{{ tag }}
          </span>
          <span v-if="extraTags" class="badge badge-ghost badge-sm text-[10px] text-base-content/35">+{{ extraTags }}</span>
        </div>
        <span v-if="!account.tags.length" class="text-[10px] text-base-content/25">no tags</span>
      </div>
      <div class="flex shrink-0 items-center gap-1.5">
        <span
          v-if="hasWarning"
          class="tooltip tooltip-top before:max-w-64"
          :data-tip="account.last_refresh_error || account.last_refresh_warning"
        >
          <span class="text-warning/80" aria-label="Refresh warning">⚠</span>
        </span>
        <span class="hidden text-[10px] text-base-content/30 sm:inline">{{ timeAgo(account.last_refreshed_at) }}</span>
        <button
          type="button"
          class="btn btn-xs gap-1.5 border-base-content/10 bg-base-300/40 font-medium hover:border-primary/40 hover:bg-primary/10"
          :disabled="busy"
          @click="emit('refresh', account)"
        >
          <span v-if="busy" class="loading loading-spinner loading-xs" />
          <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12a9 9 0 1 1-2.64-6.36" />
            <path d="M21 3v6h-6" />
          </svg>
          {{ refreshLabel }}
        </button>
      </div>
    </div>
  </article>
</template>
