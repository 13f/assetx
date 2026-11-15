<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, ApiError } from '../api'
import type { ChainMeta, Token } from '../types'
import ChainIcon from './ChainIcon.vue'

const props = defineProps<{
  token: Token
  chains: ChainMeta[]
}>()

const emit = defineEmits<{
  close: []
  saved: []
}>()

const supportedChains = computed(() => props.chains.filter((item) => item.supports_tokens))
const chain = ref('')
const contract = ref('')
const decimals = ref(6)
const saving = ref(false)
const error = ref('')

const selectedChain = computed(() => supportedChains.value.find((item) => item.id === chain.value))
const existing = computed(() => props.token.networks.find((item) => item.chain === chain.value))

function initialize() {
  const preferred =
    supportedChains.value.find((item) => !props.token.networks.some((network) => network.chain === item.id)) ??
    supportedChains.value[0]
  chain.value = preferred?.id ?? ''
}

watch(
  chain,
  () => {
    const current = existing.value
    contract.value = current?.contract_address ?? ''
    decimals.value = current?.decimals ?? (chain.value === 'ethereum' ? 18 : 6)
  },
  { immediate: true },
)

initialize()

const fieldLabel = computed(() => {
  if (chain.value === 'ethereum') return 'ERC-20 contract address'
  if (chain.value === 'solana') return 'SPL mint address'
  if (chain.value === 'cosmos') return 'Bank denom'
  return 'Contract / identifier'
})

const placeholder = computed(() => {
  if (chain.value === 'ethereum') return '0x…'
  if (chain.value === 'solana') return 'Base58 mint address'
  if (chain.value === 'cosmos') return 'uatom or ibc/…'
  return ''
})

async function submit() {
  if (!chain.value) return
  error.value = ''
  saving.value = true
  try {
    await api.upsertNetwork(props.token.id, chain.value, {
      contract_address: contract.value.trim(),
      decimals: Number(decimals.value),
      enabled: true,
    })
    emit('saved')
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Could not save this network.'
  } finally {
    saving.value = false
  }
}

function onBackdrop(event: MouseEvent) {
  if (event.target === event.currentTarget) emit('close')
}
</script>

<template>
  <div class="modal modal-open modal-bottom sm:modal-middle" @click="onBackdrop">
    <div class="modal-box max-w-lg border border-base-content/10 bg-base-200 p-0">
      <div class="border-b border-base-content/10 px-6 py-5">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-primary">{{ token.symbol }} network</p>
            <h2 class="mt-1 font-display text-xl font-semibold">{{ existing ? 'Edit network' : 'Add network' }}</h2>
          </div>
          <button class="btn btn-ghost btn-sm btn-circle text-base-content/40" type="button" @click="emit('close')">✕</button>
        </div>
      </div>
      <form class="space-y-4 px-6 py-5" @submit.prevent="submit">
        <label class="form-control">
          <span class="label-text mb-1.5 text-xs font-semibold uppercase tracking-wider text-base-content/45">Chain</span>
          <select v-model="chain" class="select select-bordered bg-base-100/60" required>
            <option v-for="item in supportedChains" :key="item.id" :value="item.id">{{ item.name }} · {{ item.token_standard }}</option>
          </select>
        </label>
        <div v-if="selectedChain" class="flex items-center gap-2 rounded-box bg-base-100/35 px-3 py-2 text-xs text-base-content/45">
          <ChainIcon :chain="selectedChain.id" :accent="selectedChain.accent" size="sm" />
          <span>{{ selectedChain.name }} · {{ selectedChain.token_standard }}</span>
          <span v-if="existing" class="badge badge-warning badge-soft badge-xs ml-auto">updating existing</span>
        </div>
        <label class="form-control">
          <span class="label-text mb-1.5 text-xs font-semibold uppercase tracking-wider text-base-content/45">{{ fieldLabel }}</span>
          <input v-model="contract" class="input input-bordered bg-base-100/60 font-mono text-sm" :placeholder="placeholder" required />
        </label>
        <label class="form-control">
          <span class="label-text mb-1.5 text-xs font-semibold uppercase tracking-wider text-base-content/45">Decimals</span>
          <input v-model.number="decimals" type="number" min="0" max="36" class="input input-bordered bg-base-100/60" required />
          <span class="mt-1 text-[11px] text-base-content/30">Base-unit precision used to format balances. USDC/USDT are usually 6; ERC-20 often 18.</span>
        </label>
        <div v-if="error" class="alert alert-error py-2 text-sm">{{ error }}</div>
        <div class="flex justify-end gap-2 border-t border-base-content/10 pt-4">
          <button type="button" class="btn btn-ghost btn-sm" @click="emit('close')">Cancel</button>
          <button type="submit" class="btn btn-primary btn-sm" :disabled="saving || !contract.trim()">
            <span v-if="saving" class="loading loading-spinner loading-xs" />
            Save network
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
