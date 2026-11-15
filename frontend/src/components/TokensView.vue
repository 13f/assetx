<script setup lang="ts">
import { computed, ref } from 'vue'
import { api, ApiError } from '../api'
import type { ChainMeta, Token } from '../types'
import { useToasts } from '../composables/useToasts'
import { formatPrice, shortAddress, timeAgo } from '../utils/format'
import AddTokenModal from './AddTokenModal.vue'
import ChainIcon from './ChainIcon.vue'
import TokenBadge from './TokenBadge.vue'
import TokenNetworkModal from './TokenNetworkModal.vue'

const props = defineProps<{
  tokens: Token[]
  chains: ChainMeta[]
  loading: boolean
}>()

const emit = defineEmits<{
  changed: []
}>()

const { push, success, error: toastError } = useToasts()
const showAddToken = ref(false)
const editingToken = ref<Token | null>(null)
const removeBusy = ref<number | null>(null)
const refreshingPrices = ref(false)

const networkCount = computed(() => props.tokens.reduce((total, token) => total + token.networks.length, 0))
const pricedCount = computed(() => props.tokens.filter((token) => token.price_usd).length)
const chainMap = computed(() => new Map(props.chains.map((chain) => [chain.id, chain])))

function tokenChain(token: Token) {
  return token.networks[0]?.chain ?? 'ethereum'
}

function chainName(chainId: string) {
  return chainMap.value.get(chainId as ChainMeta['id'])?.name ?? chainId
}

function standardFor(chainId: string) {
  return chainMap.value.get(chainId as ChainMeta['id'])?.token_standard ?? 'token'
}

async function removeNetwork(token: Token, chain: string) {
  if (!window.confirm(`Remove ${token.symbol} on ${chainName(chain)}? Saved balances for this contract will be deleted.`)) return
  removeBusy.value = token.id
  try {
    await api.deleteNetwork(token.id, chain)
    success(`${token.symbol} removed from ${chainName(chain)}`)
    emit('changed')
  } catch (err) {
    toastError(err instanceof ApiError ? err.message : 'Could not remove network.')
  } finally {
    removeBusy.value = null
  }
}

async function removeToken(token: Token) {
  if (!window.confirm(`Delete ${token.symbol} from the registry? All saved balances for this token will be deleted.`)) return
  try {
    await api.deleteToken(token.id)
    success(`${token.symbol} deleted`)
    emit('changed')
  } catch (err) {
    toastError(err instanceof ApiError ? err.message : 'Could not delete token.')
  }
}

function onSaved() {
  editingToken.value = null
  emit('changed')
}

function onCreated() {
  showAddToken.value = false
  emit('changed')
  push('Token created. Add a network contract next.')
}

async function refreshPrices() {
  refreshingPrices.value = true
  try {
    const result = await api.refreshPrices()
    if (result.warning) {
      push(result.warning, 'warning')
    } else {
      success(`Updated ${result.updated} token price${result.updated === 1 ? '' : 's'}`)
    }
    emit('changed')
  } catch (err) {
    toastError(err instanceof ApiError ? err.message : 'Could not refresh prices.')
  } finally {
    refreshingPrices.value = false
  }
}
</script>

<template>
  <section class="space-y-6">
    <div class="flex flex-col justify-between gap-4 md:flex-row md:items-end">
      <div>
        <p class="text-[11px] font-semibold uppercase tracking-[0.2em] text-primary">Registry</p>
        <h1 class="mt-1 font-display text-3xl font-semibold tracking-tight">Tokens & contracts</h1>
        <p class="mt-2 max-w-xl text-sm leading-relaxed text-base-content/45">
          One token can have a different contract, mint or bank denom on each supported chain. Native assets are seeded and locked.
        </p>
      </div>
      <div class="flex items-center gap-2">
        <button type="button" class="btn btn-ghost btn-sm border border-base-content/10" :disabled="refreshingPrices" @click="refreshPrices">
          <span v-if="refreshingPrices" class="loading loading-spinner loading-xs" />
          Refresh prices
        </button>
        <button type="button" class="btn btn-primary btn-sm" @click="showAddToken = true">+ Add token</button>
      </div>
    </div>

    <div class="grid grid-cols-3 gap-2 sm:gap-3">
      <div class="rounded-box border border-base-content/10 bg-base-200/40 px-3 py-2.5 sm:px-4 sm:py-3">
        <p class="text-[10px] uppercase tracking-widest text-base-content/30">Tokens</p>
        <p class="font-display text-2xl font-semibold">{{ tokens.length }}</p>
      </div>
      <div class="rounded-box border border-base-content/10 bg-base-200/40 px-3 py-2.5 sm:px-4 sm:py-3">
        <p class="text-[10px] uppercase tracking-widest text-base-content/30">Networks</p>
        <p class="font-display text-2xl font-semibold">{{ networkCount }}</p>
      </div>
      <div class="rounded-box border border-base-content/10 bg-base-200/40 px-3 py-2.5 sm:px-4 sm:py-3">
        <p class="text-[10px] uppercase tracking-widest text-base-content/30">Priced</p>
        <p class="font-display text-2xl font-semibold">{{ pricedCount }}<span class="text-sm font-normal text-base-content/30"> / {{ tokens.length }}</span></p>
      </div>
    </div>

    <div v-if="loading" class="grid gap-4 lg:grid-cols-2">
      <div v-for="index in 4" :key="index" class="skeleton h-56 rounded-[1.4rem]" />
    </div>

    <div v-else class="grid gap-4 lg:grid-cols-2">
      <article
        v-for="token in tokens"
        :key="token.id"
        class="group rounded-[1.4rem] border border-base-content/10 bg-base-200/45 p-5 transition hover:border-primary/20"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="flex items-center gap-3">
            <TokenBadge :symbol="token.symbol" :chain="tokenChain(token)" />
            <div>
              <div class="flex items-center gap-2">
                <h2 class="font-display text-base font-semibold tracking-wide">{{ token.symbol }}</h2>
                <span v-if="token.networks.some((network) => network.is_native)" class="badge badge-ghost badge-xs">native</span>
              </div>
              <p class="text-xs text-base-content/40">{{ token.name }}</p>
            </div>
          </div>
          <div class="text-right">
            <p class="text-sm font-semibold tabular-nums">{{ formatPrice(token.price_usd) }}</p>
            <p class="text-[10px] text-base-content/25">{{ token.price_updated_at ? timeAgo(token.price_updated_at) : 'no price yet' }}</p>
          </div>
        </div>

        <div class="mt-4 space-y-1.5">
          <div
            v-for="network in token.networks"
            :key="network.id"
            class="flex items-center gap-2.5 rounded-xl border border-base-content/[0.06] bg-base-100/30 px-2.5 py-2"
          >
            <ChainIcon :chain="network.chain" :accent="chainMap.get(network.chain)?.accent" size="sm" />
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-1.5">
                <p class="text-xs font-medium">{{ chainName(network.chain) }}</p>
                <span v-if="!network.is_native" class="text-[9px] uppercase tracking-wide text-base-content/25">{{ standardFor(network.chain) }}</span>
                <span v-else class="text-[9px] uppercase tracking-wide text-base-content/25">native</span>
              </div>
              <p class="truncate font-mono text-[10px] text-base-content/35">
                {{ network.is_native ? 'Native asset' : shortAddress(network.contract_address ?? '', 12, 8) }}
              </p>
            </div>
            <span class="shrink-0 rounded-md bg-base-300/50 px-1.5 py-0.5 text-[9px] text-base-content/40">{{ network.decimals }}d</span>
            <span v-if="network.is_native" class="shrink-0 text-[10px] text-base-content/25" title="Native network cannot be removed">●</span>
            <button
              v-else
              type="button"
              class="btn btn-ghost btn-xs btn-circle h-6 min-h-0 w-6 text-base-content/30 hover:text-error"
              :disabled="removeBusy === token.id"
              title="Remove network"
              @click="removeNetwork(token, network.chain)"
            >
              ✕
            </button>
          </div>
          <div v-if="!token.networks.length" class="rounded-xl border border-dashed border-base-content/10 px-3 py-3 text-center text-xs text-base-content/30">
            No contracts attached yet.
          </div>
        </div>

        <div class="mt-4 flex items-center justify-between border-t border-base-content/[0.07] pt-3">
          <div class="flex items-center gap-1.5 text-[10px] text-base-content/25">
            <span v-if="token.coingecko_id" class="font-mono">coingecko:{{ token.coingecko_id }}</span>
            <span v-else>no price id</span>
          </div>
          <div class="flex items-center gap-1">
            <button type="button" class="btn btn-ghost btn-xs text-[11px]" @click="editingToken = token">+ Network</button>
            <div class="dropdown dropdown-end">
              <button tabindex="0" type="button" class="btn btn-ghost btn-xs btn-circle">⋯</button>
              <ul tabindex="0" class="dropdown-content menu z-20 mt-1 w-40 rounded-box border border-base-content/10 bg-base-200 p-1.5 text-xs shadow-xl">
                <li>
                  <button type="button" @click="editingToken = token">Add / edit network</button>
                </li>
                <li>
                  <button
                    type="button"
                    class="text-error"
                    :disabled="token.networks.some((network) => network.is_native)"
                    @click="removeToken(token)"
                  >
                    Delete token
                  </button>
                </li>
              </ul>
            </div>
          </div>
        </div>
      </article>
    </div>

    <div v-if="!loading && !tokens.length" class="rounded-[1.4rem] border border-dashed border-base-content/10 py-16 text-center">
      <p class="font-display text-lg">No tokens in the registry</p>
      <button type="button" class="btn btn-primary btn-sm mt-4" @click="showAddToken = true">Add the first token</button>
    </div>

    <AddTokenModal v-if="showAddToken" @close="showAddToken = false" @created="onCreated" />
    <TokenNetworkModal v-if="editingToken" :token="editingToken" :chains="chains" @close="editingToken = null" @saved="onSaved" />
  </section>
</template>
