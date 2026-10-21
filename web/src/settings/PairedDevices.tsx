import { useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Laptop,
  Monitor,
  Plug,
  RefreshCw,
  ShieldCheck,
  Smartphone,
  Trash2,
} from "lucide-react";
import { api } from "../api";
import { Badge, Button, Card, IconTile } from "../ui";
import { useToast } from "../toast";
import { confirmDialog } from "../dialogs";

export interface PairedDevice {
  id: string;
  host: string;
  device_name?: string;
  created?: string | number;
  expires?: string | number;
  last_used?: string | number | null;
}

interface NotificationItem {
  id: string;
  code: string;
  message: string;
  expires?: number;
}

export default function PairedDevicesSection() {
  const toast = useToast();

  const [devices, setDevices] = useState<PairedDevice[]>([]);
  const [loading, setLoading] = useState<boolean>(true);

  // Pairing challenge state
  const [pairingActive, setPairingActive] = useState<boolean>(false);
  const [challengeId, setChallengeId] = useState<string>("");
  const [code, setCode] = useState<string>("");
  const [expiresAt, setExpiresAt] = useState<number>(0);
  const [secondsLeft, setSecondsLeft] = useState<number>(0);
  const [starting, setStarting] = useState<boolean>(false);

  const loadDevices = async () => {
    setLoading(true);
    try {
      const res = await api<{ devices: PairedDevice[] }>("GET", "/api/pair/devices");
      setDevices(res.devices || []);
    } catch (e: any) {
      toast("error", e.message || "Failed to load paired devices");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadDevices();
  }, []);

  // Expiry countdown timer
  useEffect(() => {
    if (!pairingActive || !expiresAt) return;

    const tick = () => {
      const diff = Math.max(0, Math.round(expiresAt - Date.now() / 1000));
      setSecondsLeft(diff);
      if (diff <= 0) {
        setPairingActive(false);
        setCode("");
      }
    };

    tick();
    const interval = window.setInterval(tick, 1000);
    return () => window.clearInterval(interval);
  }, [pairingActive, expiresAt]);

  // Start Pairing
  const startPairing = async () => {
    setStarting(true);
    setCode("");
    setChallengeId("");
    try {
      const res = await api<{ id: string; expires: number; message: string }>("POST", "/api/pair/start");
      setChallengeId(res.id);
      setExpiresAt(res.expires);
      setPairingActive(true);

      // Fetch code from approval notifications (human channel only)
      let foundCode = "";
      for (let attempt = 0; attempt < 8; attempt++) {
        try {
          const notices = await api<{ notifications: NotificationItem[] }>("GET", "/api/approval-notifications");
          const match = (notices.notifications || []).find((n) => n.id === res.id);
          if (match && match.code) {
            foundCode = match.code;
            setCode(match.code);
            break;
          }
        } catch {
          // continue retry
        }
        await new Promise((r) => setTimeout(r, 400));
      }

      if (!foundCode) {
        // Fallback message
        toast("info", "Pairing challenge started. Check your notifications or terminal for the code.");
      } else {
        toast("ok", "Pairing code generated. Enter it on your device.");
      }
    } catch (e: any) {
      toast("error", e.message);
      setPairingActive(false);
    } finally {
      setStarting(false);
    }
  };

  // Revoke device
  const revokeDevice = async (d: PairedDevice) => {
    const label = d.device_name || d.host || d.id;
    if (
      !(await confirmDialog(
        `Revoke access for paired device "${label}" (${d.host})? It will immediately lose access to project media and proposal creation.`,
        { title: "Revoke Device", ok: "Revoke Device", danger: true }
      ))
    )
      return;

    try {
      await api("DELETE", `/api/pair/devices/${encodeURIComponent(d.id)}`);
      toast("ok", `Device "${label}" revoked.`);
      await loadDevices();
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  const formatCountdown = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}:${s < 10 ? "0" : ""}${s}`;
  };

  const getHostBadgeTone = (host: string): "lime" | "sky" | "pink" | "amber" | "violet" => {
    const h = host.toLowerCase();
    if (h.includes("premiere")) return "sky";
    if (h.includes("resolve")) return "lime";
    if (h.includes("aftereffects") || h.includes("ae")) return "violet";
    if (h.includes("blender")) return "amber";
    return "pink";
  };

  const formatDate = (val?: string | number | null) => {
    if (!val) return "never";
    const num = Number(val);
    const date = !isNaN(num) ? new Date(num * 1000) : new Date(val);
    return isNaN(date.getTime()) ? String(val) : date.toLocaleDateString();
  };

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <IconTile tone="sky"><Plug size={15} /></IconTile>
          Paired NLE Devices &amp; Panels
        </span>
      }
      sub="Connect external editing workstations (Premiere Pro, DaVinci Resolve, After Effects, Blender) with scoped, revocable tokens."
      right={
        <Button
          variant="pink"
          size="sm"
          data-testid="start-pairing-btn"
          aria-label="Start device pairing"
          disabled={starting}
          onClick={startPairing}
        >
          <RefreshCw size={13} className={starting ? "animate-spin" : ""} />
          {starting ? "Starting..." : "Start Pairing"}
        </Button>
      }
    >
      <div className="space-y-5" data-testid="paired-devices-section">
        {/* Security & Capability Explanation */}
        <div className="rounded-xl border border-sky-500/30 bg-sky-950/30 p-3.5 text-xs text-slate-300 leading-relaxed">
          <div className="flex items-start gap-2.5">
            <ShieldCheck size={18} className="shrink-0 text-sky-400 mt-0.5" />
            <div>
              <b className="text-white block mb-0.5">Device Permission Model:</b>
              Paired devices can read approved project media and create proposals for your review.
              <b> Devices cannot approve spending.</b> All financial approvals require an interactive human session.
            </div>
          </div>
        </div>

        {/* Pairing Active Challenge Card */}
        {pairingActive && (
          <div
            className="rounded-2xl border border-brand/40 bg-brand/5 p-4 space-y-3"
            data-testid="pairing-active-card"
          >
            <div className="flex items-center justify-between border-b border-brand/20 pb-2.5">
              <span className="text-xs font-bold uppercase tracking-wider text-brand flex items-center gap-1.5">
                <Clock size={14} /> Active Pairing Challenge
              </span>
              <span
                className="font-mono text-xs font-bold text-slate-300"
                data-testid="pairing-countdown"
                aria-label={`Code expires in ${formatCountdown(secondsLeft)}`}
              >
                Expires in {formatCountdown(secondsLeft)}
              </span>
            </div>

            <div className="text-center py-3">
              <p className="text-xs text-slate-400 mb-2">
                Enter this 6-digit code in the NLE panel prompt to link your device:
              </p>
              {code ? (
                <div
                  className="font-mono text-4xl font-extrabold tracking-[0.25em] text-brand select-all"
                  data-testid="pairing-code"
                  aria-label={`Pairing code ${code}`}
                >
                  {code}
                </div>
              ) : (
                <div className="flex items-center justify-center gap-2 text-sm text-slate-400">
                  <RefreshCw size={16} className="animate-spin text-brand" />
                  Generating secure code...
                </div>
              )}
            </div>

            <p className="text-[11px] text-slate-400 text-center">
              This code is visible only in your human browser session and terminal stderr. It cannot be read by API keys or background agents.
            </p>
          </div>
        )}

        {/* Device List */}
        <div>
          <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3">
            Connected Devices
          </h4>

          {loading ? (
            <p className="text-sm text-slate-400 py-4 text-center">Loading devices...</p>
          ) : devices.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-800 p-6 text-center text-sm text-slate-400">
              No paired devices connected yet. Click "Start Pairing" above to link Premiere Pro, DaVinci Resolve, After Effects, or Blender.
            </div>
          ) : (
            <ul className="divide-y divide-slate-800" data-testid="paired-device-list">
              {devices.map((d) => (
                <li
                  key={d.id}
                  className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm"
                  data-testid={`device-row-${d.id}`}
                >
                  <div className="min-w-0 space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-slate-100">
                        {d.device_name || d.host || "Unnamed Device"}
                      </span>
                      <Badge tone={getHostBadgeTone(d.host || "")}>{d.host || "device"}</Badge>
                    </div>

                    <div className="flex flex-wrap items-center gap-3 text-xs text-slate-400 font-mono">
                      <span>ID: {d.id.slice(0, 8)}...</span>
                      <span>Created: {formatDate(d.created)}</span>
                      <span>Expires: {formatDate(d.expires)}</span>
                      <span>Last used: {formatDate(d.last_used)}</span>
                    </div>
                  </div>

                  <Button
                    variant="outline"
                    size="sm"
                    data-testid={`revoke-device-${d.id}`}
                    aria-label={`Revoke device ${d.device_name || d.host || d.id}`}
                    onClick={() => revokeDevice(d)}
                  >
                    <Trash2 size={13} /> Revoke
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Card>
  );
}
