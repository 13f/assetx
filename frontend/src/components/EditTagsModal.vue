<script setup lang="ts">
import { ref } from 'vue'
import { api, ApiError } from '../api'
import type { Account } from '../types'
import TagInput from './TagInput.vue'
import { shortAddress } from '../utils/format'

const props = defineProps<{
  account: Account
}>()

const emit = defineEmits<{
  close: []
  updated: []
}>()

const tags = ref<string[]>([...props.account.tags])
const saving = ref(false)
const error = ref('')

async function save() {
  saving.value = true
  error.value = ''
  try {
    await api.updateTags(props.account.id, tags.value)
    emit('updated')
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : 'Could not update tags.'
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
    <div class="modal-box max-w-md border border-base-content/10 bg-base-200 p-0 shadow-2xl">
      <div class="border-b border-base-content/10 px-6 py-5">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-primary">Edit account</p>
            <h2 class="mt-1 font-display text-xl font-semibold">Tags</h2>
          </div>
          <button class="btn btn-ghost btn-sm btn-circle text-base-content/40" type="button" aria-label="Close" @click="emit('close')">✕</button>
        </div>
        <p class="mt-2 font-mono text-xs text-base-content/40">{{ account.chain_name }} · {{ shortAddress(account.address, 10, 6) }}</p>
      </div>

      <form class="space-y-4 px-6 py-5" @submit.prevent="save">
        <TagInput v-model="tags" />
        <div v-if="error" class="alert alert-error py-2 text-sm">{{ error }}</div>
        <div class="flex justify-end gap-2 border-t border-base-content/10 pt-4">
          <button type="button" class="btn btn-ghost btn-sm" @click="emit('close')">Cancel</button>
          <button type="submit" class="btn btn-primary btn-sm" :disabled="saving">
            <span v-if="saving" class="loading loading-spinner loading-xs" />
            Save tags
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
