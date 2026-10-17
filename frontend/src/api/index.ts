import { httpApi } from './http'
import { mockApi } from './mock'
import type { ZobaApi } from './types'

export const USING_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'

export const api: ZobaApi = USING_MOCK ? mockApi : httpApi

export * from './types'
