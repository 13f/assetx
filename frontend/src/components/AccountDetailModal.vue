<script setup lang="ts">
import type { Account } from '../types'
import { formatAmount, formatPrice, formatUsd, shortAddress, timeAgo } from '../utils/format'
import ChainIcon from './ChainIcon.vue'
import TokenBadge from './TokenBadge.vue'

defineProps<{
  account: Account
}>()

const emit = defineEmits<{
  close: []
  refresh: [account: Account]
  edit: [account: Account]
}>()

function onBackdrop(event: MouseEvent) {
  if (event.target === event.currentTarget) emit('close')
}
</script>

<template>
  <div class="modal modal-open modal-bottom sm:modal-middle" @click="onBackdrop">
    <div class="modal-box max-w-2xl border border-base-content/10 bg-base-200 p-0 shadow-2xl">
      <div class="relative overflow-hidden border-b border-base-content/10 px-6 py-5">
        <div class="pointer-events-none absolute -right-16 -top-20 h-48 w-48 rounded-full bg-primary/10 blur-3xl" />
        <button class="btn btn-ghost btn-sm btn-circle absolute right-3 top-3 text-base-content/40" type="button" aria-label="Close" @click="emit('close')">✕</button>
        <div class="flex items-center gap-3">
          <ChainIcon :chain="account.chain" :accent="account.accent" size="lg" />
          <div class="min-w-0">
            <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-primary">{{ account.chain_name }} account</p>
            <h2 class="truncate font-mono text-sm font-medium text-base-content/80">{{ shortAddress(account.address, 14, 8) }}</h2>
          </div>
        </div>
        <div class="mt-5 flex flex-wrap items-end justify-between gap-3">
          <div>
            <p class="text-[11px] uppercase tracking-widest text-base-content/35">Total balance</p>
            <p class="font-display text-3xl font-semibold">{{ formatUsd(account.total_usd) }}</p>
          </div>
          <div class="flex flex-wrap gap-1.5">
            <span v-for="tag in account.tags" :key="tag" class="badge badge-soft badge-primary badge-sm">#{{ tag }}</span>
            <span v-if="!account.tags.length" class="badge badge-ghost badge-sm">no tags</span>
          </div>
        </div>
        <div class="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-base-content/35">
          <span>Updated {{ timeAgo(account.last_refreshed_at) }}</span>
          <span v-if="account.last_refresh_provider">via {{ account.last_refresh_provider }}</span>
          <span>{{ account.tracked_token_count }} tracked asset{{ account.tracked_token_count === 1 ? '' : 's' }}</span>
        </div>
      </div>

      <div class="max-h-[45vh] overflow-y-auto px-3 py-3">
        <div v-if="account.tokens.length" class="space-y-1">
          <div
            v-for="token in account.tokens"
            :key="token.network_id"
            class="flex items-center justify-between gap-3 rounded-box px-3 py-2.5 transition hover:bg-base-content/[0.04]"
          >
            <div class="flex min-w-0 items-center gap-3">
              <TokenBadge :symbol="token.symbol" :chain="account.chain" />
              <div class="min-w-0">
                <div class="flex items-center gap-2">
                  <p class="text-sm font-semibold">{{ token.symbol }}</p>
                  <span v-if="token.is_native" class="badge badge-ghost badge-xs">native</span>
                </div>
                <p class="truncate text-[11px] text-base-content/35">{{ token.name }}</p>
              </div>
            </div>
            <div class="text-right">
              <p class="text-sm tabular-nums text-base-content/80">{{ formatAmount(token.balance) }} <span class="text-[10px] text-base-content/30">{{ token.symbol }}</span></p>
              <p class="text-[11px] tabular-nums text-base-content/35">
                {{ formatUsd(token.value_usd) }}
                <span v-if="token.price_usd" class="text-base-content/25"> · {{ formatPrice(token.price_usd) }}</span>
              </p>
            </div>
          </div>
        </div>
        <div v-else class="flex min-h-40 flex-col items-center justify-center gap-2 text-center">
          <span class="text-2xl opacity-25">◌</span>
          <p class="text-sm text-base-content/40">No saved balances</p>
          <p class="text-xs text-base-content/25">Refresh this address to fetch its assets.</p>
        </div>

        <div v-if="account.last_refresh_warning" class="mx-2 mt-3 rounded-box border border-warning/20 bg-warning/5 px-3 py-2 text-[11px] leading-relaxed text-warning/80">
          ⚠ {{ account.last_refresh_warning }}
        </div>
        <div v-if="account.last_refresh_error" class="mx-2 mt-3 rounded-box border border-error/20 bg-error/5 px-3 py-2 text-[11px] leading-relaxed text-error/80">
          ✕ {{ account.last_refresh_error }}
        </div>
      </div>

      <div class="flex items-center justify-between gap-2 border-t border-base-content/10 px-6 py-4">
        <button type="button" class="btn btn-ghost btn-sm" @click="emit('edit', account)">Edit tags</button>
        <div class="flex gap-2">
          <button type="button" class="btn btn-ghost btn-sm" @click="emit('close')">Close</button>
          <button type="button" class="btn btn-primary btn-sm" @click="emit('refresh', account)">Refresh assets</button>
        </div>
      </div>
    </div>
  </div>
</template>
