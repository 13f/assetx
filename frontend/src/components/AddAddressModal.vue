<script setup lang="ts">
import { computed, ref } from 'vue'
import { api, ApiError } from '../api'
import type { ChainMeta } from '../types'
import ChainIcon from './ChainIcon.vue'
import TagInput from './TagInput.vue'

const props = defineProps<{
  chains: ChainMeta[]
}>()

const emit = defineEmits<{
  close: []
  created: []
}>()

const chain = ref('')
const address = ref('')
const tags = ref<string[]>([])
const submitting = ref(false)
const error = ref('')

const selectedChain = computed(() => props.chains.find((item) => item.id === chain.value))
const canSubmit = computed(() => Boolean(chain.value && address.value.trim() && !submitting.value))

async function submit() {
  error.value = ''
  if (!chain.value) {
    error.value = 'Choose a blockchain first.'
    return
  }
  if (!address.value.trim()) {
    error.value = 'Enter a wallet address.'
    return
  }
  submitting.value = true
  try {
    await api.createAccount({
      chain: chain.value,
      address: address.value.trim(),
      tags: tags.value,
    })
    emit('created')
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Could not add this address.'
  } finally {
    submitting.value = false
  }
}

function onBackdrop(event: MouseEvent) {
  if (event.target === event.currentTarget) emit('close')
}
</script>

<template>
  <div class="modal modal-open modal-bottom sm:modal-middle" @click="onBackdrop">
    <div class="modal-box max-w-xl overflow-hidden border border-base-content/10 bg-base-200 p-0 shadow-2xl">
      <div class="relative overflow-hidden border-b border-base-content/10 px-6 pb-5 pt-6">
        <div class="pointer-events-none absolute -right-14 -top-16 h-44 w-44 rounded-full bg-primary/10 blur-3xl" />
        <button class="btn btn-ghost btn-sm btn-circle absolute right-3 top-3 text-base-content/40" type="button" aria-label="Close" @click="emit('close')">✕</button>
        <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-primary">New account</p>
        <h2 class="mt-1 font-display text-2xl font-semibold tracking-tight">Track a blockchain address</h2>
        <p class="mt-1.5 max-w-md text-sm leading-relaxed text-base-content/45">
          AssetX only reads public chain data. Add an address, optionally tag it, then run a manual refresh.
        </p>
      </div>

      <form class="space-y-5 px-6 py-5" @submit.prevent="submit">
        <div class="grid gap-4 sm:grid-cols-[1.1fr_0.9fr]">
          <label class="form-control">
            <span class="label-text mb-2 text-xs font-semibold uppercase tracking-wider text-base-content/45">
              Blockchain <span class="text-error">*</span>
            </span>
            <select v-model="chain" class="select select-bordered w-full bg-base-100/60" required>
              <option value="" disabled>Select a chain…</option>
              <option v-for="item in chains" :key="item.id" :value="item.id">
                {{ item.name }} · {{ item.native_symbol }}
              </option>
            </select>
          </label>

          <div class="rounded-box border border-base-content/10 bg-base-100/35 p-3">
            <template v-if="selectedChain">
              <div class="flex items-center gap-2.5">
                <ChainIcon :chain="selectedChain.id" :accent="selectedChain.accent" size="sm" />
                <div>
                  <p class="text-sm font-semibold">{{ selectedChain.name }}</p>
                  <p class="text-[11px] text-base-content/35">{{ selectedChain.provider_count }} public endpoints · failover</p>
                </div>
              </div>
              <div class="mt-2.5 flex flex-wrap gap-1.5">
                <span class="badge badge-ghost badge-sm text-[10px]">{{ selectedChain.native_symbol }} native</span>
                <span v-if="selectedChain.supports_tokens" class="badge badge-ghost badge-sm text-[10px]">{{ selectedChain.token_standard }}</span>
                <span v-else class="badge badge-ghost badge-sm text-[10px]">native only</span>
                <span v-if="selectedChain.supports_nft_positions" class="badge badge-ghost badge-sm text-[10px]">Uniswap V3 LP</span>
              </div>
            </template>
            <p v-else class="flex h-full items-center text-xs leading-relaxed text-base-content/35">
              Pick a chain to see its address format and token support.
            </p>
          </div>
        </div>

        <label class="form-control">
          <span class="label-text mb-2 text-xs font-semibold uppercase tracking-wider text-base-content/45">Address</span>
          <input
            v-model="address"
            type="text"
            class="input input-bordered w-full bg-base-100/60 font-mono text-sm"
            :placeholder="selectedChain?.address_placeholder ?? 'Select a chain, then paste the address'"
            autocomplete="off"
            spellcheck="false"
            required
          />
          <span class="mt-1.5 text-xs text-base-content/35">
            {{ selectedChain?.address_hint ?? 'Each address belongs to one blockchain.' }}
          </span>
        </label>

        <div>
          <span class="label-text mb-2 mt-1 block text-xs font-semibold uppercase tracking-wider text-base-content/45">
            Tags <span class="font-normal normal-case tracking-normal text-base-content/25">optional</span>
          </span>
          <TagInput v-model="tags" />
        </div>

        <div v-if="error" role="alert" class="alert alert-error border-error/30 bg-error/10 py-2.5 text-sm">
          <span>{{ error }}</span>
        </div>

        <div class="flex items-center justify-between gap-3 border-t border-base-content/10 pt-4">
          <p class="max-w-[18rem] text-[11px] leading-relaxed text-base-content/30">
            No private keys, no signatures. Public RPCs only.
          </p>
          <div class="flex gap-2">
            <button type="button" class="btn btn-ghost btn-sm" @click="emit('close')">Cancel</button>
            <button type="submit" class="btn btn-primary btn-sm px-5" :disabled="!canSubmit">
              <span v-if="submitting" class="loading loading-spinner loading-xs" />
              Add account
            </button>
          </div>
        </div>
      </form>
    </div>
  </div>
</template>
