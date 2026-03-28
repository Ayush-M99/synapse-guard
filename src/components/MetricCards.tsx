import {
  Shield,
  Clock,
  Zap,
  Server,
  Activity,
  Lock,
  Globe,
  Cpu,
} from "lucide-react";

const glass =
  "backdrop-blur-xl border rounded-lg px-4 py-3 border-border/20 bg-card/40";

interface MetricProps {
  icon: React.ReactNode;
  label: string;
  value: string | React.ReactNode;
  sub?: string;
}

function Metric({ icon, label, value, sub }: MetricProps) {
  return (
    <div className={`${glass} min-w-[140px]`}>
      <div className="flex items-center gap-2 text-muted-foreground text-[11px] uppercase tracking-wider mb-1.5">
        {icon}
        {label}
      </div>
      <div className="text-xl font-semibold text-foreground tabular-nums leading-tight">
        {value}
      </div>
      {sub && (
        <div className="text-[10px] text-muted-foreground mt-0.5">{sub}</div>
      )}
    </div>
  );
}

export function MetricCards() {
  return (
    <div className="absolute top-16 left-0 right-0 z-10 pointer-events-none">
      <div className="flex items-start justify-between px-6 pt-4 gap-3 pointer-events-auto flex-wrap">
        {/* Left cluster */}
        <div className="flex gap-3 flex-wrap">
          <Metric
            icon={<Shield className="w-3.5 h-3.5" />}
            label="Threats Blocked"
            value="12,847"
            sub="Last 24h"
          />
          <Metric
            icon={<Activity className="w-3.5 h-3.5" />}
            label="Incidents"
            value={
              <span className="flex items-center gap-2">
                0
                <span className="text-[10px] font-normal px-1.5 py-0.5 rounded bg-success/10 text-success border border-success/20">
                  ALL CLEAR
                </span>
              </span>
            }
            sub="Active threats"
          />
          <Metric
            icon={<Lock className="w-3.5 h-3.5" />}
            label="Encryption"
            value="AES-256"
            sub="End-to-end"
          />
        </div>

        {/* Right cluster */}
        <div className="flex gap-3 flex-wrap">
          <Metric
            icon={<Clock className="w-3.5 h-3.5" />}
            label="Uptime"
            value={
              <span className="flex items-center gap-2">
                99.97%
                <span className="w-2 h-2 rounded-full bg-success inline-block animate-pulse" />
              </span>
            }
            sub="30-day average"
          />
          <Metric
            icon={<Zap className="w-3.5 h-3.5" />}
            label="Latency"
            value="< 8ms"
            sub="p99 response"
          />
          <Metric
            icon={<Cpu className="w-3.5 h-3.5" />}
            label="CPU Load"
            value="23%"
            sub="Avg across nodes"
          />
        </div>
      </div>
    </div>
  );
}
