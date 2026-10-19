import { Button } from "@/components/ui/button"
import { Layers, Rocket, ShieldCheck } from "lucide-react"

function App() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col items-center justify-center p-6">
      <div className="max-w-xl w-full bg-slate-900 border border-slate-800 rounded-2xl p-8 shadow-2xl space-y-6">
        <div className="flex items-center space-x-3">
          <div className="p-3 bg-blue-600/20 text-blue-400 rounded-xl">
            <Layers className="w-8 h-8" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white tracking-tight">Finance Command Center</h1>
            <p className="text-sm text-slate-400">Vite + React + TypeScript + Tailwind v4 + shadcn/ui</p>
          </div>
        </div>

        <div className="p-4 bg-slate-800/50 rounded-xl border border-slate-700/50 space-y-2 text-sm text-slate-300">
          <div className="flex items-center space-x-2 text-emerald-400 font-medium">
            <ShieldCheck className="w-4 h-4" />
            <span>Frontend setup successfully ready!</span>
          </div>
          <p className="text-xs text-slate-400">
            Source directory: <code className="bg-slate-900 px-2 py-0.5 rounded text-slate-200">src/frontend/src</code>
          </p>
        </div>

        <div className="flex gap-3">
          <Button className="bg-blue-600 hover:bg-blue-500 text-white font-medium shadow-lg shadow-blue-500/20">
            <Rocket className="w-4 h-4 mr-2" /> Get Started
          </Button>
          <Button variant="outline" className="border-slate-700 text-slate-200 hover:bg-slate-800 hover:text-white">
            Documentation
          </Button>
        </div>
      </div>
    </div>
  )
}

export default App
