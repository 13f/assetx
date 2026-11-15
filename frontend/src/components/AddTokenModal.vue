<script setup lang="ts">
import { ref } from 'vue'
import { api, ApiError } from '../api'

const emit = defineEmits<{
  close: []
  created: []
}>()

const symbol = ref('')
const name = ref('')
const coingeckoId = ref('')
const saving = ref(false)
const error = ref('')

async function submit() {
  error.value = ''
  saving.value = true
  try {
    await api.createToken({
      symbol: symbol.value.trim(),
      name: name.value.trim(),
      coingecko_id: coingeckoId.value.trim() || null,
    })
    emit('created')
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Could not create token.'
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
    <div class="modal-box max-w-md border border-base-content/10 bg-base-200 p-0">
      <div class="border-b border-base-content/10 px-6 py-5">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-primary">Token registry</p>
            <h2 class="mt-1 font-display text-xl font-semibold">Add a token</h2>
          </div>
          <button class="btn btn-ghost btn-sm btn-circle text-base-content/40" type="button" @click="emit('close')">✕</button>
        </div>
        <p class="mt-2 text-sm text-base-content/40">Create the asset first, then attach one contract or denom per supported chain.</p>
      </div>
      <form class="space-y-4 px-6 py-5" @submit.prevent="submit">
        <label class="form-control">
          <span class="label-text mb-1.5 text-xs font-semibold uppercase tracking-wider text-base-content/45">Symbol</span>
          <input v-model="symbol" class="input input-bordered bg-base-100/60 uppercase" placeholder="e.g. LINK" maxlength="16" required />
        </label>
        <label class="form-control">
          <span class="label-text mb-1.5 text-xs font-semibold uppercase tracking-wider text-base-content/45">Name</span>
          <input v-model="name" class="input input-bordered bg-base-100/60" placeholder="e.g. Chainlink" maxlength="80" required />
        </label>
        <label class="form-control">
          <span class="label-text mb-1.5 text-xs font-semibold uppercase tracking-wider text-base-content/45">CoinGecko id <span class="font-normal normal-case text-base-content/25">optional, for USD price</span></span>
          <input v-model="coingeckoId" class="input input-bordered bg-base-100/60 font-mono text-sm" placeholder="chainlink" maxlength="120" />
        </label>
        <div v-if="error" class="alert alert-error py-2 text-sm">{{ error }}</div>
        <div class="flex justify-end gap-2 border-t border-base-content/10 pt-4">
          <button type="button" class="btn btn-ghost btn-sm" @click="emit('close')">Cancel</button>
          <button type="submit" class="btn btn-primary btn-sm" :disabled="saving || !symbol.trim() || !name.trim()">
            <span v-if="saving" class="loading loading-spinner loading-xs" />
            Create token
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
