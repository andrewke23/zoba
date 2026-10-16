import type { ReactNode } from 'react'
import { Logo, MockBanner } from './AppShell'

export default function AuthLayout({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <MockBanner />
      <div className="flex flex-1 items-center justify-center bg-gradient-to-br from-brand-50 via-stone-50 to-orange-50 px-4 py-10">
        <div className="w-full max-w-sm">
          <div className="mb-6 flex justify-center">
            <Logo />
          </div>
          <div className="rounded-2xl border border-stone-200 bg-white p-6 shadow-sm">
            <h1 className="text-xl font-bold text-stone-900">{title}</h1>
            <p className="mt-1 mb-5 text-sm text-stone-600">{subtitle}</p>
            {children}
          </div>
        </div>
      </div>
    </div>
  )
}
