<script setup lang="ts">
import { ref } from 'vue'
import { api, ApiError } from '../api'
import type { Account } from '../types'
import { shortAddress } from '../utils/format'

const props = defineProps<{
  account: Account
}>()

const emit = defineEmits<{
  close: []
  deleted: []
}>()

const deleting = ref(false)
const error = ref('')

async function remove() {
  deleting.value = true
  error.value = ''
  try {
    await api.deleteAccount(props.account.id)
    emit('deleted')
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Could not remove this address.'
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <div class="modal modal-open modal-bottom sm:modal-middle">
    <div class="modal-box max-w-sm border border-base-content/10 bg-base-200">
      <div class="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-error/10 text-xl text-error">!</div>
      <h3 class="mt-4 text-center font-display text-lg font-semibold">Remove this address?</h3>
      <p class="mt-2 text-center font-mono text-xs text-base-content/45">{{ shortAddress(account.address, 10, 6) }}</p>
      <p class="mt-3 text-center text-sm leading-relaxed text-base-content/45">
        Its saved balances and refresh history will be deleted. This does not affect the wallet itself.
      </p>
      <div v-if="error" class="alert alert-error mt-4 py-2 text-sm">{{ error }}</div>
      <div class="mt-5 grid grid-cols-2 gap-2">
        <button type="button" class="btn btn-ghost btn-sm" @click="emit('close')">Cancel</button>
        <button type="button" class="btn btn-error btn-sm" :disabled="deleting" @click="remove">
          <span v-if="deleting" class="loading loading-spinner loading-xs" />
          Remove
        </button>
      </div>
    </div>
  </div>
</template>
