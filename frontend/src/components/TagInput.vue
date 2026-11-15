<script setup lang="ts">
import { ref } from 'vue'

const props = withDefaults(
  defineProps<{
    modelValue: string[]
    max?: number
    placeholder?: string
    disabled?: boolean
  }>(),
  { max: 10, placeholder: 'Add a tag and press Enter', disabled: false },
)

const emit = defineEmits<{
  'update:modelValue': [value: string[]]
}>()

const draft = ref('')
const error = ref('')

function commit() {
  const value = draft.value.trim().replace(/\s+/g, ' ').toLowerCase()
  if (!value) {
    draft.value = ''
    return
  }
  if (value.length > 32) {
    error.value = 'Tags can be up to 32 characters.'
    return
  }
  if (props.modelValue.includes(value)) {
    draft.value = ''
    return
  }
  if (props.modelValue.length >= props.max) {
    error.value = `You can add up to ${props.max} tags.`
    return
  }
  error.value = ''
  emit('update:modelValue', [...props.modelValue, value])
  draft.value = ''
}

function remove(tag: string) {
  error.value = ''
  emit(
    'update:modelValue',
    props.modelValue.filter((item) => item !== tag),
  )
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' || event.key === ',') {
    event.preventDefault()
    commit()
  } else if (event.key === 'Backspace' && !draft.value && props.modelValue.length) {
    remove(props.modelValue[props.modelValue.length - 1])
  }
}
</script>

<template>
  <div>
    <div
      class="flex min-h-12 flex-wrap items-center gap-2 rounded-box border border-base-content/10 bg-base-200/60 px-3 py-2 transition focus-within:border-primary/60 focus-within:ring-2 focus-within:ring-primary/20"
    >
      <span
        v-for="tag in modelValue"
        :key="tag"
        class="badge badge-soft badge-primary gap-1.5 py-2.5 font-medium"
      >
        #{{ tag }}
        <button
          type="button"
          class="text-primary/70 transition hover:text-primary"
          :aria-label="`Remove tag ${tag}`"
          @click="remove(tag)"
        >
          ✕
        </button>
      </span>
      <input
        v-model="draft"
        class="min-w-32 flex-1 bg-transparent text-sm outline-none placeholder:text-base-content/35"
        :placeholder="modelValue.length ? 'Add another…' : placeholder"
        :disabled="disabled || modelValue.length >= max"
        maxlength="40"
        @keydown="onKeydown"
        @blur="commit"
      />
      <span class="text-[11px] tabular-nums text-base-content/35">{{ modelValue.length }}/{{ max }}</span>
    </div>
    <p v-if="error" class="mt-1.5 text-xs text-error">{{ error }}</p>
    <p v-else class="mt-1.5 text-xs text-base-content/40">Tags are stored lowercase. Press Enter or comma to add.</p>
  </div>
</template>
