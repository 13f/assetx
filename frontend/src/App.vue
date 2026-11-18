<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, ApiError } from './api'
import type { Account, ChainMeta, QueueStatus, Token } from './types'
import { formatUsd, timeAgo } from './utils/format'
import { useToasts } from './composables/useToasts'
import AccountCard from './components/AccountCard.vue'
import AccountDetailModal from './components/AccountDetailModal.vue'
import AddAddressModal from './components/AddAddressModal.vue'
import ChainCard from './components/ChainCard.vue'
import ChainIcon from './components/ChainIcon.vue'
import ConfirmDeleteModal from './components/ConfirmDeleteModal.vue'
import EditTagsModal from './components/EditTagsModal.vue'
import QueueIndicator from './components/QueueIndicator.vue'
import ToastStack from './components/ToastStack.vue'
import TokensView from './components/TokensView.vue'

const { success, error: toastError, info } = useToasts()

const chains = ref<ChainMeta[]>([])
const accounts = ref<Account[]>([])
const tokens = ref<Token[]>([])
const queue = ref<QueueStatus | null>(null)
const loading = ref(true)
const tokensLoading = ref(false)
const loadError = ref('')
const activeTab = ref<'accounts' | 'tokens'>('accounts')
const search = ref('')
const chainFilter = ref('all')
const tagFilter = ref('all')

const showAddAddress = ref(false)
const editAccount = ref<Account | null>(null)
const deleteTarget = ref<Account | null>(null)
const detailAccount = ref<Account | null>(null)
const refreshingAll = ref(false)

let pollTimer: number | undefined
let wasActive = 0
let pollInFlight = false

const chainMap = computed(() => new Map(chains.value.map((chain) => [chain.id, chain])))
const activeCount = computed(() => (queue.value?.counts.queued ?? 0) + (queue.value?.counts.running ?? 0))
const totalUsd = computed(() =>
  accounts.value.reduce((total, account) => total + Number(account.total_usd || 0), 0),
)
const chainCounts = computed(() => {
  const counts = new Map<string, number>()
  for (const account of accounts.value) {
    counts.set(account.chain, (counts.get(account.chain) ?? 0) + 1)
  }
  return counts
})

interface ChainSummary {
  chain: ChainMeta
  totalUsd: number
  share: number
  accountCount: number
  lastSyncedAt: string | null
  status: Account['total_status']
}
const chainSummaries = computed<ChainSummary[]>(() => {
  const portfolioTotal = totalUsd.value
  return chains.value.map((chain) => {
    const chainAccounts = accounts.value.filter((account) => account.chain === chain.id)
    const chainTotal = chainAccounts.reduce((sum, account) => sum + Number(account.total_usd || 0), 0)
    let status: Account['total_status'] = 'complete'
    if (chainAccounts.some((account) => account.total_status === 'partial')) status = 'partial'
    else if (chainAccounts.some((account) => account.total_status === 'stale')) status = 'stale'
    const syncTimes = chainAccounts
      .map((account) => account.last_refreshed_at)
      .filter((value): value is string => Boolean(value))
      .sort()
    return {
      chain,
      totalUsd: chainTotal,
      share: portfolioTotal > 0 ? (chainTotal / portfolioTotal) * 100 : 0,
      accountCount: chainAccounts.length,
      lastSyncedAt: syncTimes.length ? syncTimes[syncTimes.length - 1] : null,
      status,
    }
  })
})
const allTags = computed(() => {
  const tags = new Set<string>()
  for (const account of accounts.value) {
    for (const tag of account.tags) tags.add(tag)
  }
  return [...tags].sort()
})
const lastSynced = computed(() => {
  const dates = accounts.value
    .map((account) => account.last_refreshed_at)
    .filter((value): value is string => Boolean(value))
    .sort()
  return dates.length ? dates[dates.length - 1] : null
})
const filteredAccounts = computed(() => {
  const needle = search.value.trim().toLowerCase()
  return accounts.value.filter((account) => {
    if (chainFilter.value !== 'all' && account.chain !== chainFilter.value) return false
    if (tagFilter.value !== 'all' && !account.tags.includes(tagFilter.value)) return false
    if (!needle) return true
    return (
      account.address.toLowerCase().includes(needle) ||
      account.chain_name.toLowerCase().includes(needle) ||
      account.tags.some((tag) => tag.includes(needle))
    )
  })
})
const hasFilters = computed(() => Boolean(search.value || chainFilter.value !== 'all' || tagFilter.value !== 'all'))

async function loadChains() {
  const response = await api.chains()
  chains.value = response.items
}

async function loadAccounts() {
  const response = await api.accounts()
  accounts.value = response.items
}

async function loadTokens() {
  tokensLoading.value = true
  try {
    const response = await api.tokens()
    tokens.value = response.items
  } finally {
    tokensLoading.value = false
  }
}

async function loadQueue() {
  queue.value = await api.queueStatus()
  wasActive = (queue.value.counts.queued ?? 0) + (queue.value.counts.running ?? 0)
}

async function loadAll() {
  loading.value = true
  loadError.value = ''
  try {
    await Promise.all([loadChains(), loadAccounts(), loadQueue()])
  } catch (err) {
    loadError.value = err instanceof ApiError ? err.message : 'Could not load AssetX data.'
  } finally {
    loading.value = false
  }
}

async function poll() {
  if (pollInFlight || document.hidden) return
  pollInFlight = true
  try {
    const status = await api.queueStatus()
    queue.value = status
    const nowActive = (status.counts.queued ?? 0) + (status.counts.running ?? 0)
    if (wasActive > 0 && nowActive === 0) {
      await loadAccounts()
      if (activeTab.value === 'tokens') await loadTokens()
      if (detailAccount.value) await refreshOpenDetail()
      info('Refresh queue finished.')
    }
    wasActive = nowActive
  } catch {
    // Polling is best-effort; surface real action errors elsewhere.
  } finally {
    pollInFlight = false
  }
}

async function refreshOpenDetail() {
  if (!detailAccount.value) return
  try {
    detailAccount.value = await api.account(detailAccount.value.id)
  } catch {
    detailAccount.value = null
  }
}

async function refreshAccount(account: Account) {
  try {
    const response = await api.refreshAccount(account.id)
    if (response.job.deduplicated) {
      info('This address is already in the refresh queue.')
    } else {
      success(`Queued ${account.chain_name} · ${account.address.slice(0, 8)}…`)
    }
    await Promise.all([loadQueue(), loadAccounts()])
    if (detailAccount.value?.id === account.id) await refreshOpenDetail()
  } catch (err) {
    toastError(err instanceof ApiError ? err.message : 'Could not queue refresh.')
  }
}

async function refreshAll() {
  if (!accounts.value.length) return
  refreshingAll.value = true
  try {
    const response = await api.refreshAll()
    if (response.count === 0) {
      info('Nothing to refresh.')
    } else {
      success(`Queued ${response.count} address${response.count === 1 ? '' : 'es'} with a ${queue.value?.interval_seconds ?? 3}s gap.`)
    }
    await Promise.all([loadQueue(), loadAccounts()])
  } catch (err) {
    toastError(err instanceof ApiError ? err.message : 'Could not queue refreshes.')
  } finally {
    refreshingAll.value = false
  }
}

async function openDetails(account: Account) {
  try {
    detailAccount.value = await api.account(account.id)
  } catch (err) {
    toastError(err instanceof ApiError ? err.message : 'Could not load account details.')
  }
}

function openEdit(account: Account) {
  detailAccount.value = null
  editAccount.value = account
}

function confirmDelete(account: Account) {
  detailAccount.value = null
  deleteTarget.value = account
}

async function onAddressCreated() {
  showAddAddress.value = false
  await loadAccounts()
  success('Address added. Run a refresh to fetch balances.')
}

async function onTagsUpdated() {
  editAccount.value = null
  await loadAccounts()
  await refreshOpenDetail()
  success('Tags updated.')
}

async function onAddressDeleted() {
  deleteTarget.value = null
  await loadAccounts()
  await loadQueue()
  success('Address removed.')
}

async function onRegistryChanged() {
  await Promise.all([loadTokens(), loadAccounts()])
}

function clearFilters() {
  search.value = ''
  chainFilter.value = 'all'
  tagFilter.value = 'all'
}

function toggleChainSummary(chain: ChainMeta) {
  if (!chainCounts.value.get(chain.id)) return
  chainFilter.value = chainFilter.value === chain.id ? 'all' : chain.id
}

watch(activeTab, (tab) => {
  if (tab === 'tokens' && !tokens.value.length) loadTokens().catch(() => undefined)
})

onMounted(async () => {
  await loadAll()
  pollTimer = window.setInterval(poll, 2500)
})

onUnmounted(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<template>
  <div class="min-h-screen">
    <header class="sticky top-0 z-40 border-b border-base-content/[0.07] bg-base-100/75 backdrop-blur-xl">
      <div class="app-shell flex h-16 items-center gap-3">
        <button type="button" class="group flex items-center gap-2.5" @click="activeTab = 'accounts'">
          <span class="flex h-9 w-9 items-center justify-center rounded-xl border border-primary/25 bg-primary/10">
            <svg width="21" height="21" viewBox="0 0 64 64" fill="none" aria-hidden="true">
              <path d="M18 40.5 32 14l14 26.5-14 8z" fill="#6ee7b7" />
              <path d="m18 45.5 14 8 14-8-14 15z" fill="#38bdf8" opacity=".55" />
            </svg>
          </span>
          <span class="font-display text-lg font-semibold tracking-tight">Asset<span class="text-primary">X</span></span>
          <span class="badge badge-ghost badge-xs hidden text-[9px] uppercase tracking-wider text-base-content/35 sm:inline">self-custody</span>
        </button>

        <nav class="ml-2 hidden items-center gap-0.5 rounded-xl border border-base-content/[0.06] bg-base-200/40 p-1 sm:flex">
          <button
            type="button"
            class="rounded-lg px-3 py-1.5 text-xs font-medium transition"
            :class="activeTab === 'accounts' ? 'bg-base-content/10 text-base-content shadow-sm' : 'text-base-content/45 hover:text-base-content/80'"
            @click="activeTab = 'accounts'"
          >
            Accounts
            <span class="ml-1 text-[10px] text-base-content/30">{{ accounts.length }}</span>
          </button>
          <button
            type="button"
            class="rounded-lg px-3 py-1.5 text-xs font-medium transition"
            :class="activeTab === 'tokens' ? 'bg-base-content/10 text-base-content shadow-sm' : 'text-base-content/45 hover:text-base-content/80'"
            @click="activeTab = 'tokens'"
          >
            Tokens
          </button>
        </nav>

        <div class="ml-auto flex items-center gap-2">
          <QueueIndicator :queue="queue" />
          <button
            type="button"
            class="btn btn-ghost btn-sm hidden h-9 border border-base-content/10 px-3 text-xs md:inline-flex"
            :disabled="!accounts.length || refreshingAll || activeCount > 0"
            @click="refreshAll"
          >
            <span v-if="refreshingAll" class="loading loading-spinner loading-xs" />
            <svg v-else width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 12a9 9 0 1 1-2.64-6.36" />
              <path d="M21 3v6h-6" />
            </svg>
            Refresh all
          </button>
          <button type="button" class="btn btn-primary btn-sm h-9 gap-1.5 px-3.5" @click="showAddAddress = true">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round">
              <path d="M12 5v14M5 12h14" />
            </svg>
            <span class="hidden sm:inline">Add address</span>
            <span class="sm:hidden">Add</span>
          </button>
        </div>
      </div>

      <div class="app-shell pb-2 sm:hidden">
        <div class="grid grid-cols-2 gap-1 rounded-xl border border-base-content/[0.06] bg-base-200/40 p-1">
          <button
            type="button"
            class="rounded-lg py-1.5 text-xs font-medium transition"
            :class="activeTab === 'accounts' ? 'bg-base-content/10 text-base-content' : 'text-base-content/45'"
            @click="activeTab = 'accounts'"
          >
            Accounts <span class="text-[10px] text-base-content/30">{{ accounts.length }}</span>
          </button>
          <button
            type="button"
            class="rounded-lg py-1.5 text-xs font-medium transition"
            :class="activeTab === 'tokens' ? 'bg-base-content/10 text-base-content' : 'text-base-content/45'"
            @click="activeTab = 'tokens'"
          >
            Tokens
          </button>
        </div>
      </div>
    </header>

    <main class="app-shell pb-20 pt-6 sm:pt-8">
      <div v-if="loadError" class="alert alert-error mb-5 border-error/30 bg-error/10">
        <span>{{ loadError }}</span>
        <button type="button" class="btn btn-ghost btn-xs" @click="loadAll">Retry</button>
      </div>

      <template v-if="activeTab === 'accounts'">
        <div v-if="loading" class="space-y-5">
          <div class="skeleton h-48 rounded-[1.6rem]" />
          <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <div v-for="index in 3" :key="index" class="skeleton h-[19rem] rounded-[1.4rem]" />
          </div>
        </div>

        <template v-else>
          <section class="glow-ring relative overflow-hidden rounded-[1.6rem] border border-base-content/10 bg-base-200/50 p-6 backdrop-blur sm:p-7">
            <div class="pointer-events-none absolute -right-24 -top-32 h-80 w-80 rounded-full bg-primary/10 blur-3xl" />
            <div class="pointer-events-none absolute -bottom-40 left-1/3 h-72 w-72 rounded-full bg-secondary/10 blur-3xl" />
            <div class="relative flex flex-col justify-between gap-7 lg:flex-row lg:items-end">
              <div class="max-w-xl">
                <div class="flex items-center gap-2">
                  <p class="eyebrow">Portfolio overview</p>
                  <span class="inline-flex h-1 w-1 rounded-full bg-base-content/20" />
                  <p class="text-[11px] text-base-content/35">{{ accounts.length }} account{{ accounts.length === 1 ? '' : 's' }} across {{ chainCounts.size }} chain{{ chainCounts.size === 1 ? '' : 's' }}</p>
                </div>
                <p class="mt-2 font-display text-4xl font-semibold tracking-tight sm:text-5xl">
                  {{ formatUsd(totalUsd) }}
                </p>
                <div class="mt-4 flex flex-wrap items-center gap-2">
                  <span class="badge badge-ghost badge-sm border-base-content/10 text-base-content/45">
                    Last sync {{ lastSynced ? timeAgo(lastSynced) : 'never' }}
                  </span>
                  <span v-if="queue" class="badge badge-ghost badge-sm border-base-content/10 text-base-content/45">
                    {{ queue.interval_seconds }}s queue gap
                  </span>
                  <span v-if="queue?.worker_running" class="badge badge-soft badge-success badge-sm gap-1">
                    <span class="h-1.5 w-1.5 rounded-full bg-success" /> worker online
                  </span>
                </div>
              </div>

              <div class="flex flex-col items-start gap-3 lg:items-end">
                <div class="flex flex-wrap gap-1.5">
                  <button
                    v-for="chain in chains"
                    :key="chain.id"
                    type="button"
                    class="flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] transition"
                    :class="chainFilter === chain.id ? 'border-primary/40 bg-primary/10 text-primary' : 'border-base-content/10 bg-base-100/30 text-base-content/45 hover:border-base-content/20'"
                    @click="chainFilter = chainFilter === chain.id ? 'all' : chain.id"
                  >
                    <span class="h-1.5 w-1.5 rounded-full" :style="{ backgroundColor: chain.accent }" />
                    {{ chain.native_symbol }}
                    <span class="text-base-content/25">{{ chainCounts.get(chain.id) ?? 0 }}</span>
                  </button>
                </div>
                <div class="flex gap-2">
                  <button type="button" class="btn btn-sm border-base-content/10 bg-base-100/40" :disabled="activeCount > 0 || !accounts.length" @click="refreshAll">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M21 12a9 9 0 1 1-2.64-6.36" />
                      <path d="M21 3v6h-6" />
                    </svg>
                    Refresh all
                  </button>
                  <button type="button" class="btn btn-primary btn-sm" @click="showAddAddress = true">Add account</button>
                </div>
              </div>
            </div>
          </section>

          <section v-if="accounts.length" class="mt-6">
            <div class="mb-3 flex items-end justify-between gap-3">
              <div>
                <p class="eyebrow">Chain allocation</p>
                <h2 class="mt-1 font-display text-base font-semibold tracking-tight">Assets by chain</h2>
              </div>
              <p class="hidden text-[11px] text-base-content/30 sm:block">Select a chain to filter accounts</p>
            </div>
            <div class="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
              <ChainCard
                v-for="(summary, index) in chainSummaries"
                :key="summary.chain.id"
                :chain="summary.chain"
                :total-usd="summary.totalUsd"
                :share="summary.share"
                :account-count="summary.accountCount"
                :last-synced-at="summary.lastSyncedAt"
                :status="summary.status"
                :active="chainFilter === summary.chain.id"
                class="grid-fade"
                :style="{ animationDelay: `${Math.min(index, 6) * 30}ms` }"
                @toggle="toggleChainSummary"
              />
            </div>
          </section>

          <div class="mt-6 flex flex-col gap-3 lg:flex-row lg:items-center">
            <label class="input input-bordered flex h-10 flex-1 items-center gap-2 border-base-content/10 bg-base-200/40 text-sm focus-within:border-primary/40">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-base-content/30">
                <circle cx="11" cy="11" r="7" />
                <path d="m20 20-3.2-3.2" />
              </svg>
              <input v-model="search" class="grow bg-transparent text-sm outline-none placeholder:text-base-content/30" placeholder="Search address, chain or tag…" />
              <kbd v-if="search" class="kbd kbd-xs cursor-pointer" @click="search = ''">clear</kbd>
            </label>
            <div class="flex items-center gap-2">
              <select v-if="allTags.length" v-model="tagFilter" class="select select-bordered select-sm h-10 border-base-content/10 bg-base-200/40 text-xs">
                <option value="all">All tags</option>
                <option v-for="tag in allTags" :key="tag" :value="tag">#{{ tag }}</option>
              </select>
              <button v-if="hasFilters" type="button" class="btn btn-ghost btn-sm h-10 text-xs" @click="clearFilters">Clear filters</button>
              <span class="hidden text-[11px] text-base-content/30 sm:inline">{{ filteredAccounts.length }} shown</span>
            </div>
          </div>

          <div v-if="accounts.length && filteredAccounts.length" class="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <AccountCard
              v-for="(account, index) in filteredAccounts"
              :key="account.id"
              :account="account"
              :chain="chainMap.get(account.chain)"
              class="grid-fade"
              :style="{ animationDelay: `${Math.min(index, 6) * 35}ms` }"
              @refresh="refreshAccount"
              @edit="openEdit"
              @delete="confirmDelete"
              @details="openDetails"
            />
          </div>

          <div v-else-if="accounts.length" class="mt-5 rounded-[1.4rem] border border-dashed border-base-content/10 py-20 text-center">
            <p class="font-display text-lg text-base-content/65">No accounts match those filters</p>
            <button type="button" class="btn btn-ghost btn-sm mt-3" @click="clearFilters">Clear filters</button>
          </div>

          <section v-else class="relative mt-5 overflow-hidden rounded-[1.6rem] border border-dashed border-base-content/12 px-6 py-20 text-center">
            <div class="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_0%,rgba(110,231,183,0.08),transparent_55%)]" />
            <div class="relative mx-auto flex max-w-md flex-col items-center">
              <div class="flex -space-x-2">
                <ChainIcon v-for="chain in chains" :key="chain.id" :chain="chain.id" :accent="chain.accent" size="md" class="ring-4 ring-base-100" />
              </div>
              <h2 class="mt-6 font-display text-2xl font-semibold tracking-tight">Your portfolio starts with one address</h2>
              <p class="mt-2 text-sm leading-relaxed text-base-content/45">
                Add a public wallet address on Ethereum, Solana, Bitcoin, Nervos, Cosmos or Stacks. AssetX discovers native and configured token balances, plus Uniswap V3 LP positions on Ethereum, and prices them in USD.
              </p>
              <div class="mt-6 flex gap-2">
                <button type="button" class="btn btn-primary btn-sm px-5" @click="showAddAddress = true">Add your first address</button>
                <button type="button" class="btn btn-ghost btn-sm" @click="activeTab = 'tokens'">View token registry</button>
              </div>
              <div class="mt-8 grid w-full grid-cols-3 gap-1.5 sm:grid-cols-6">
                <div v-for="chain in chains" :key="chain.id" class="rounded-lg border border-base-content/[0.06] bg-base-200/35 px-1 py-2">
                  <p class="text-[10px] font-semibold">{{ chain.native_symbol }}</p>
                  <p class="mt-0.5 text-[9px] text-base-content/25">{{ chain.provider_count }} RPCs</p>
                </div>
              </div>
            </div>
          </section>
        </template>
      </template>

      <TokensView
        v-else
        :tokens="tokens"
        :chains="chains"
        :loading="tokensLoading"
        @changed="onRegistryChanged"
      />
    </main>

    <footer class="border-t border-base-content/[0.06] py-6">
      <div class="app-shell flex flex-col justify-between gap-3 text-[11px] text-base-content/25 sm:flex-row sm:items-center">
        <p>AssetX · public chain data only. No private keys. Not financial advice.</p>
        <div class="flex items-center gap-4">
          <a class="transition hover:text-base-content/60" href="/api/docs" target="_blank" rel="noopener">API docs ↗</a>
          <span>Ethereum · Solana · Bitcoin · Nervos · Cosmos · Stacks</span>
        </div>
      </div>
    </footer>

    <AddAddressModal v-if="showAddAddress" :chains="chains" @close="showAddAddress = false" @created="onAddressCreated" />
    <EditTagsModal v-if="editAccount" :account="editAccount" @close="editAccount = null" @updated="onTagsUpdated" />
    <ConfirmDeleteModal v-if="deleteTarget" :account="deleteTarget" @close="deleteTarget = null" @deleted="onAddressDeleted" />
    <AccountDetailModal
      v-if="detailAccount"
      :account="detailAccount"
      @close="detailAccount = null"
      @edit="openEdit"
      @refresh="refreshAccount"
    />
    <ToastStack />
  </div>
</template>
