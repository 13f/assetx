<script setup lang="ts">
import { computed } from 'vue'
import type { QueueStatus } from '../types'
import { shortAddress, timeAgo } from '../utils/format'

const props = defineProps<{
  queue: QueueStatus | null
}>()

const activeCount = computed(() => (props.queue?.counts.queued ?? 0) + (props.queue?.counts.running ?? 0))
const isActive = computed(() => activeCount.value > 0)
const label = computed(() => {
  if (!props.queue?.worker_running) return 'Worker off'
  if (!isActive.value) return 'Queue idle'
  if (props.queue.counts.running) {
    return props.queue.counts.queued ? `Working · ${props.queue.counts.queued}` : 'Working'
  }
  return `${props.queue.counts.queued} queued`
})
</script>

<template>
  <div class="dropdown dropdown-end">
    <button
      tabindex="0"
      type="button"
      class="btn btn-sm h-9 gap-2 border-base-content/10 bg-base-200/50 px-2.5 font-normal"
      :class="{ 'border-primary/25 bg-primary/5': isActive }"
      aria-label="Refresh queue status"
    >
      <span
        class="inline-flex h-2 w-2 rounded-full"
        :class="isActive ? 'animate-pulse bg-primary' : queue?.worker_running ? 'bg-success/60' : 'bg-error/60'"
      />
      <span class="max-w-24 truncate text-[10px] text-base-content/60">{{ label }}</span>
      <span v-if="isActive" class="badge badge-primary badge-xs">{{ activeCount }}</span>
    </button>
    <div tabindex="0" class="dropdown-content z-30 mt-2 w-80 rounded-box border border-base-content/10 bg-base-200 p-4 shadow-2xl">
      <div class="flex items-center justify-between">
        <div>
          <p class="text-[11px] font-semibold uppercase tracking-widest text-base-content/35">Refresh queue</p>
          <p class="mt-0.5 text-xs text-base-content/55">
            {{ queue?.worker_running ? 'Sequential worker online' : 'Worker is not running' }}
          </p>
        </div>
        <span class="badge badge-ghost badge-sm">{{ queue?.interval_seconds ?? 3 }}s gap</span>
      </div>
      <div class="mt-3 grid grid-cols-4 gap-1.5">
        <div class="rounded-lg bg-base-300/40 p-2 text-center">
          <p class="font-display text-lg font-semibold">{{ queue?.counts.queued ?? 0 }}</p>
          <p class="text-[9px] uppercase tracking-wider text-base-content/30">queued</p>
        </div>
        <div class="rounded-lg bg-base-300/40 p-2 text-center">
          <p class="font-display text-lg font-semibold text-primary">{{ queue?.counts.running ?? 0 }}</p>
          <p class="text-[9px] uppercase tracking-wider text-base-content/30">running</p>
        </div>
        <div class="rounded-lg bg-base-300/40 p-2 text-center">
          <p class="font-display text-lg font-semibold">{{ queue?.counts.success ?? 0 }}</p>
          <p class="text-[9px] uppercase tracking-wider text-base-content/30">done</p>
        </div>
        <div class="rounded-lg bg-base-300/40 p-2 text-center">
          <p class="font-display text-lg font-semibold text-error">{{ queue?.counts.failed ?? 0 }}</p>
          <p class="text-[9px] uppercase tracking-wider text-base-content/30">failed</p>
        </div>
      </div>
      <div v-if="queue?.active.length" class="mt-3 space-y-1.5">
        <div
          v-for="job in queue.active"
          :key="job.id"
          class="flex items-center justify-between gap-2 rounded-lg border border-base-content/5 bg-base-100/30 px-2.5 py-2"
        >
          <div class="flex min-w-0 items-center gap-2">
            <span v-if="job.status === 'running'" class="loading loading-spinner loading-xs text-primary" />
            <span v-else class="inline-block h-2 w-2 rounded-full border border-base-content/30" />
            <span class="truncate font-mono text-[10px] text-base-content/55">{{ shortAddress(job.address ?? '—', 8, 5) }}</span>
          </div>
          <span class="shrink-0 text-[10px] text-base-content/30">{{ job.status }} · {{ timeAgo(job.started_at ?? job.created_at) }}</span>
        </div>
      </div>
      <p v-else class="mt-3 rounded-lg border border-dashed border-base-content/10 px-3 py-4 text-center text-xs text-base-content/30">
        Nothing in the queue. Refresh an account to start.
      </p>
      <p class="mt-3 text-[10px] leading-relaxed text-base-content/25">
        Addresses are processed one at a time with a {{ queue?.interval_seconds ?? 3 }} second gap to avoid public endpoint rate limits.
      </p>
    </div>
  </div>
</template>
