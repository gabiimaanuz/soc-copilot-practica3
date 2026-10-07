"use client";

import { useRequireAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

const IP_REGEX_G = /\b(?:\d{1,3}\.){3}\d{1,3}\b/g;
const MAC_REGEX = /\b(?:[0-9A-Fa-f]{2}[:-]){5}(?:[0-9A-Fa-f]{2})\b/;
const PROTO_TOKENS = ["TCP", "UDP", "ICMP", "HTTPS", "HTTP", "SSH", "DNS", "FTP", "SMTP", "TLS", "ARP"];
const PROTO_REGEX = new RegExp(`\\b(${PROTO_TOKENS.join("|")})\\b`);

interface ParsedLine {
  id: number;
  text: string;
  ts: number | null;
  srcIp: string | null;
  dstIp: string | null;
  srcPort: number | null;
  dstPort: number | null;
  mac: string | null;
  proto: string | null;
}

function extractTimestamp(line: string): number | null {
  const syslogMatch = line.match(/^[A-Z][a-z]{2}\s+\d+\s+\d{2}:\d{2}:\d{2}/);
  if (syslogMatch) {
    const d = new Date(`${syslogMatch[0]} ${new Date().getFullYear()}`);
    if (!isNaN(d.getTime())) return d.getTime();
  }

  const webMatch = line.match(/\[(\d{2}\/[A-Za-z]{3}\/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4})\]/);
  if (webMatch) {
    const str = webMatch[1].replace(":", " ");
    const d = new Date(str);
    if (!isNaN(d.getTime())) return d.getTime();
  }

  const isoMatch = line.match(/\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b/);
  if (isoMatch) {
    const d = new Date(isoMatch[0]);
    if (!isNaN(d.getTime())) return d.getTime();
  }

  return null;
}

function toPort(raw: string | undefined | null): number | null {
  if (!raw) return null;
  const n = parseInt(raw, 10);
  return Number.isFinite(n) && n >= 0 && n <= 65535 ? n : null;
}

function parseLine(text: string): Omit<ParsedLine, "id" | "text" | "ts"> {
  let srcIp: string | null = null;
  let dstIp: string | null = null;
  let srcPort: number | null = null;
  let dstPort: number | null = null;
  let proto: string | null = null;

  const kv = text.match(
    /SRC=(\d{1,3}(?:\.\d{1,3}){3}).{0,150}?DST=(\d{1,3}(?:\.\d{1,3}){3})/i,
  );
  if (kv) {
    srcIp = kv[1];
    dstIp = kv[2];
  }
  const sptMatch = text.match(/SPT=(\d{1,5})/i);
  const dptMatch = text.match(/DPT=(\d{1,5})/i);
  if (sptMatch) srcPort = toPort(sptMatch[1]);
  if (dptMatch) dstPort = toPort(dptMatch[1]);
  const protoKv = text.match(/PROTO=([A-Za-z]+)/i);
  if (protoKv) proto = protoKv[1].toUpperCase();

  if (!srcIp || !dstIp) {
    const arrow = text.match(
      /(\d{1,3}(?:\.\d{1,3}){3})(?::(\d{1,5}))?\s*(?:->|→|=>)\s*(\d{1,3}(?:\.\d{1,3}){3})(?::(\d{1,5}))?/,
    );
    if (arrow) {
      srcIp = srcIp ?? arrow[1];
      srcPort = srcPort ?? toPort(arrow[2]);
      dstIp = dstIp ?? arrow[3];
      dstPort = dstPort ?? toPort(arrow[4]);
    }
  }

  if (!srcIp) {
    const sshd = text.match(/from\s+(\d{1,3}(?:\.\d{1,3}){3})(?:\s+port\s+(\d{1,5}))?/i);
    if (sshd) {
      srcIp = sshd[1];
      srcPort = srcPort ?? toPort(sshd[2]);
    }
  }

  if (!srcIp || !dstIp) {
    const ips = text.match(IP_REGEX_G) ?? [];
    if (!srcIp && ips[0]) srcIp = ips[0];
    if (!dstIp && ips[1]) dstIp = ips[1];
  }

  if (!proto) {
    const m = text.match(PROTO_REGEX);
    if (m) proto = m[1].toUpperCase();
  }

  const macMatch = text.match(MAC_REGEX);

  return {
    srcIp,
    dstIp,
    srcPort,
    dstPort,
    mac: macMatch ? macMatch[0] : null,
    proto,
  };
}

const PAGE_SIZE_OPTIONS = [10, 50, 100, 150] as const;
const DEFAULT_PAGE_SIZE = 50;
const PROTO_OPTIONS = ["", ...PROTO_TOKENS];

const inputCls =
  "w-full bg-ink-950 border border-ink-700 rounded-md px-2.5 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-cyan-500/60 focus:ring-1 focus:ring-cyan-500/20 transition";

function StepHeader({ n, title, action }: { n: number; title: string; action?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <div className="flex items-center gap-2">
        <span className="w-5 h-5 grid place-items-center rounded bg-cyan-500/10 text-cyan-300 text-[10px] font-mono border border-cyan-500/20">
          {n}
        </span>
        <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
      </div>
      {action}
    </div>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="block text-[10px] uppercase tracking-widest text-slate-500 mb-1">
      {children}
    </span>
  );
}

export default function LogsAnalyzerPage() {
  const auth = useRequireAuth();
  const router = useRouter();
  const { t } = useI18n();

  const [filename, setFilename] = useState<string | null>(null);
  const [lines, setLines] = useState<ParsedLine[]>([]);

  const [searchTermInput, setSearchTermInput] = useState("");
  const [debouncedSearchTerm, setDebouncedSearchTerm] = useState("");
  const [srcIpFilter, setSrcIpFilter] = useState("");
  const [dstIpFilter, setDstIpFilter] = useState("");
  const [srcPortFilter, setSrcPortFilter] = useState("");
  const [dstPortFilter, setDstPortFilter] = useState("");
  const [macFilter, setMacFilter] = useState("");
  const [protoFilter, setProtoFilter] = useState("");
  const [requireAuthFailure, setRequireAuthFailure] = useState(false);
  const [requireHTTPError, setRequireHTTPError] = useState(false);
  const [timeFrom, setTimeFrom] = useState("");
  const [timeTo, setTimeTo] = useState("");

  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState<number>(DEFAULT_PAGE_SIZE);

  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  useEffect(() => {
    const handler = setTimeout(() => setDebouncedSearchTerm(searchTermInput), 300);
    return () => clearTimeout(handler);
  }, [searchTermInput]);

  const handleClearFilters = () => {
    setSearchTermInput("");
    setDebouncedSearchTerm("");
    setSrcIpFilter("");
    setDstIpFilter("");
    setSrcPortFilter("");
    setDstPortFilter("");
    setMacFilter("");
    setProtoFilter("");
    setRequireAuthFailure(false);
    setRequireHTTPError(false);
    setTimeFrom("");
    setTimeTo("");
    setCurrentPage(1);
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setFilename(file.name);
    const reader = new FileReader();
    reader.onload = (evt) => {
      const content = evt.target?.result as string;
      const rawLines = content.split("\n").filter((l) => l.trim() !== "");

      const parsedLines: ParsedLine[] = rawLines.map((text, idx) => ({
        id: idx,
        text,
        ts: extractTimestamp(text),
        ...parseLine(text),
      }));

      setLines(parsedLines);
      setSelectedIds(new Set());
      setCurrentPage(1);
    };
    reader.readAsText(file);
  };

  const filteredLines = useMemo(() => {
    const fromTs = timeFrom ? new Date(timeFrom).getTime() : null;
    const toTs = timeTo ? new Date(timeTo).getTime() + 59999 : null;

    const srcIpQ = srcIpFilter.trim();
    const dstIpQ = dstIpFilter.trim();
    const macQ = macFilter.trim().toLowerCase();
    const srcPortQ = srcPortFilter.trim();
    const dstPortQ = dstPortFilter.trim();
    const protoQ = protoFilter.trim().toUpperCase();

    return lines.filter((line) => {
      if (srcIpQ && (!line.srcIp || !line.srcIp.includes(srcIpQ))) return false;
      if (dstIpQ && (!line.dstIp || !line.dstIp.includes(dstIpQ))) return false;
      if (srcPortQ && String(line.srcPort ?? "") !== srcPortQ) return false;
      if (dstPortQ && String(line.dstPort ?? "") !== dstPortQ) return false;
      if (macQ && (!line.mac || !line.mac.toLowerCase().includes(macQ))) return false;
      if (protoQ && line.proto !== protoQ) return false;

      if (requireAuthFailure && !/(failed|invalid|failure|error)/i.test(line.text)) return false;
      if (requireHTTPError && !/HTTP\/[12](\.[01])?" [45]\d{2}/.test(line.text)) return false;
      if (debouncedSearchTerm && !line.text.toLowerCase().includes(debouncedSearchTerm.toLowerCase())) return false;

      if (line.ts) {
        if (fromTs && line.ts < fromTs) return false;
        if (toTs && line.ts > toTs) return false;
      } else if (fromTs || toTs) {
        return false;
      }

      return true;
    });
  }, [
    lines,
    debouncedSearchTerm,
    srcIpFilter,
    dstIpFilter,
    srcPortFilter,
    dstPortFilter,
    macFilter,
    protoFilter,
    requireAuthFailure,
    requireHTTPError,
    timeFrom,
    timeTo,
  ]);

  useEffect(() => {
    setCurrentPage(1);
  }, [filteredLines.length]);

  const totalPages = Math.ceil(filteredLines.length / pageSize) || 1;
  const paginatedLines = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredLines.slice(start, start + pageSize);
  }, [filteredLines, currentPage, pageSize]);

  useEffect(() => {
    setCurrentPage(1);
  }, [pageSize]);

  const handleToggleSelectAll = () => {
    const pageIds = paginatedLines.map((l) => l.id);
    const allSelected = pageIds.every((id) => selectedIds.has(id));

    const next = new Set(selectedIds);
    if (allSelected) {
      pageIds.forEach((id) => next.delete(id));
    } else {
      pageIds.forEach((id) => next.add(id));
    }
    setSelectedIds(next);
  };

  const handleToggleLine = (id: number) => {
    const next = new Set(selectedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedIds(next);
  };

  const handleAnalyze = () => {
    if (selectedIds.size === 0) return;

    const selectedText = lines
      .filter((l) => selectedIds.has(l.id))
      .map((l) => l.text)
      .join("\n");

    sessionStorage.setItem("soc_copilot_imported_logs", selectedText);
    router.push("/alerts?import=true");
  };

  const allPageSelected =
    paginatedLines.length > 0 && paginatedLines.every((l) => selectedIds.has(l.id));

  const startIdx = (currentPage - 1) * pageSize;

  if (!auth.ready) {
    return <div className="p-8 text-slate-500 text-sm">Verificando sesión…</div>;
  }

  return (
    <div className="p-6 max-w-[1600px] mx-auto space-y-6">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-100">
            Analizador de Logs
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Carga un archivo local, filtra y envía las líneas relevantes al
            Alert Explainer.
          </p>
        </div>
        <div className="text-right text-xs">
          <div className="text-slate-500">
            Total{" "}
            <span className="font-mono text-slate-300">{lines.length}</span> ·
            tras filtros{" "}
            <span className="font-mono text-cyan-300">{filteredLines.length}</span>
          </div>
          <div className="text-slate-500">
            Seleccionadas{" "}
            <span className="font-mono text-cyan-300">{selectedIds.size}</span>
          </div>
        </div>
      </header>

      <div className="grid grid-cols-1 xl:grid-cols-[300px_minmax(0,1fr)] gap-4">
        <aside className="space-y-4">
          <section className="rounded-xl border border-ink-700 bg-ink-900/60 p-4">
            <StepHeader n={1} title="Cargar archivo" />
            <label className="block w-full border-2 border-dashed border-ink-700 hover:border-cyan-500/40 rounded-lg p-5 text-center cursor-pointer transition group">
              <div className="text-cyan-300/80 text-2xl mb-1">⬆</div>
              <span className="text-xs text-slate-400 group-hover:text-slate-300 break-all">
                {filename ? filename : "Click para subir .log / .txt / .csv"}
              </span>
              <input
                type="file"
                accept=".log,.txt,.csv"
                onChange={handleFileUpload}
                className="hidden"
              />
            </label>
            {lines.length > 0 && (
              <p className="mt-3 text-[11px] font-mono text-cyan-400">
                {lines.length} líneas procesadas
              </p>
            )}
          </section>

          <section className="rounded-xl border border-ink-700 bg-ink-900/60 p-4 space-y-3">
            <StepHeader
              n={2}
              title="Filtros de red"
              action={
                <button
                  onClick={handleClearFilters}
                  className="text-[11px] text-slate-500 hover:text-cyan-300 transition"
                >
                  Limpiar
                </button>
              }
            />

            <label className="block">
              <FieldLabel>IP origen</FieldLabel>
              <input
                type="text"
                value={srcIpFilter}
                onChange={(e) => setSrcIpFilter(e.target.value)}
                className={`${inputCls} font-mono`}
                placeholder="192.168.1"
              />
            </label>
            <label className="block">
              <FieldLabel>IP destino</FieldLabel>
              <input
                type="text"
                value={dstIpFilter}
                onChange={(e) => setDstIpFilter(e.target.value)}
                className={`${inputCls} font-mono`}
                placeholder="10.0.0.5"
              />
            </label>

            <div className="grid grid-cols-2 gap-2">
              <label>
                <FieldLabel>Puerto orig.</FieldLabel>
                <input
                  type="number"
                  min={0}
                  max={65535}
                  value={srcPortFilter}
                  onChange={(e) => setSrcPortFilter(e.target.value)}
                  className={`${inputCls} font-mono`}
                  placeholder="41234"
                />
              </label>
              <label>
                <FieldLabel>Puerto dest.</FieldLabel>
                <input
                  type="number"
                  min={0}
                  max={65535}
                  value={dstPortFilter}
                  onChange={(e) => setDstPortFilter(e.target.value)}
                  className={`${inputCls} font-mono`}
                  placeholder="22"
                />
              </label>
            </div>

            <label className="block">
              <FieldLabel>MAC</FieldLabel>
              <input
                type="text"
                value={macFilter}
                onChange={(e) => setMacFilter(e.target.value)}
                className={`${inputCls} font-mono`}
                placeholder="aa:bb:cc"
              />
            </label>

            <label className="block">
              <FieldLabel>Protocolo</FieldLabel>
              <select
                value={protoFilter}
                onChange={(e) => setProtoFilter(e.target.value)}
                className={inputCls}
              >
                {PROTO_OPTIONS.map((p) => (
                  <option key={p} value={p}>
                    {p === "" ? "(todos)" : p}
                  </option>
                ))}
              </select>
            </label>
          </section>

          <section className="rounded-xl border border-ink-700 bg-ink-900/60 p-4 space-y-3">
            <StepHeader n={3} title="Otros filtros" />

            <label className="block">
              <FieldLabel>Texto libre</FieldLabel>
              <input
                type="text"
                value={searchTermInput}
                onChange={(e) => setSearchTermInput(e.target.value)}
                className={inputCls}
                placeholder="sshd, root, failed…"
              />
            </label>

            <div className="space-y-2 pt-1">
              <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer hover:text-slate-100">
                <input
                  type="checkbox"
                  checked={requireAuthFailure}
                  onChange={(e) => setRequireAuthFailure(e.target.checked)}
                  className="rounded bg-ink-950 border-ink-700 accent-cyan-500"
                />
                Errores de autenticación
              </label>
              <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer hover:text-slate-100">
                <input
                  type="checkbox"
                  checked={requireHTTPError}
                  onChange={(e) => setRequireHTTPError(e.target.checked)}
                  className="rounded bg-ink-950 border-ink-700 accent-cyan-500"
                />
                HTTP 4xx / 5xx
              </label>
            </div>

            <div className="pt-3 border-t border-ink-700 space-y-2">
              <FieldLabel>Periodo (heurístico)</FieldLabel>
              <input
                type="datetime-local"
                value={timeFrom}
                onChange={(e) => setTimeFrom(e.target.value)}
                className={`${inputCls} font-mono`}
              />
              <input
                type="datetime-local"
                value={timeTo}
                onChange={(e) => setTimeTo(e.target.value)}
                className={`${inputCls} font-mono`}
              />
            </div>
          </section>

          <section className="rounded-xl border border-ink-700 bg-ink-900/60 p-4 space-y-3 sticky bottom-4">
            <StepHeader n={4} title={t("alerts_analyze_btn")} />
            <p className="text-xs text-slate-400">
              Líneas seleccionadas:{" "}
              <span className="font-mono text-cyan-300">
                {selectedIds.size}
              </span>
            </p>
            <button
              onClick={handleAnalyze}
              disabled={selectedIds.size === 0}
              className="w-full py-2 rounded-md text-xs font-medium bg-cyan-500 text-ink-950 hover:bg-cyan-400 disabled:bg-ink-700 disabled:text-slate-500 disabled:cursor-not-allowed transition"
            >
              {t("alerts_analyze_btn")} →
            </button>
          </section>
        </aside>

        <section className="rounded-xl border border-ink-700 bg-ink-900/60 flex flex-col overflow-hidden min-h-[600px]">
          <div className="px-4 py-3 border-b border-ink-700 bg-ink-850 flex justify-between items-center gap-4">
            <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                checked={allPageSelected}
                onChange={handleToggleSelectAll}
                disabled={paginatedLines.length === 0}
                className="rounded bg-ink-950 border-ink-700 accent-cyan-500"
              />
              <span>
                Seleccionar página ({paginatedLines.length})
              </span>
            </label>
            <div className="flex items-center gap-3 text-[11px] text-slate-500">
              <label className="flex items-center gap-2">
                <span>Por página</span>
                <select
                  value={pageSize}
                  onChange={(e) => setPageSize(Number(e.target.value))}
                  className="bg-ink-950 border border-ink-700 rounded px-2 py-1 text-slate-200 text-xs"
                >
                  {PAGE_SIZE_OPTIONS.map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              <span className="font-mono">
                {filteredLines.length} hits
              </span>
            </div>
          </div>

          <div className="flex-1 overflow-auto bg-ink-950 font-mono text-xs">
            {lines.length === 0 ? (
              <div className="h-full min-h-[400px] flex flex-col items-center justify-center gap-2 text-slate-500">
                <div className="text-3xl text-slate-700">≡</div>
                <span>{t("tile_logs_desc")}</span>
              </div>
            ) : paginatedLines.length === 0 ? (
              <div className="h-full min-h-[400px] flex items-center justify-center text-slate-500">
                Ninguna línea coincide con los filtros en esta página.
              </div>
            ) : (
              <div className="divide-y divide-ink-800/60">
                {paginatedLines.map((line, i) => {
                  const selected = selectedIds.has(line.id);
                  return (
                    <label
                      key={line.id}
                      className={
                        "grid grid-cols-[24px_44px_1fr] gap-2 px-3 py-1.5 cursor-pointer transition " +
                        (selected
                          ? "bg-cyan-500/5 hover:bg-cyan-500/10"
                          : "hover:bg-ink-900/60")
                      }
                    >
                      <input
                        type="checkbox"
                        checked={selected}
                        onChange={() => handleToggleLine(line.id)}
                        className="mt-0.5 rounded bg-ink-900 border-ink-700 accent-cyan-500"
                      />
                      <span className="text-[10px] text-slate-600 select-none pt-0.5 text-right">
                        {String(startIdx + i + 1).padStart(4, "0")}
                      </span>
                      <div className="min-w-0">
                        <div
                          className={
                            "break-all leading-relaxed " +
                            (selected ? "text-cyan-200" : "text-slate-300")
                          }
                        >
                          {line.text}
                        </div>
                        {(line.srcIp || line.dstIp || line.proto || line.mac) && (
                          <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-slate-500">
                            {line.srcIp && (
                              <span>
                                src{" "}
                                <span className="text-slate-300">
                                  {line.srcIp}
                                  {line.srcPort != null && `:${line.srcPort}`}
                                </span>
                              </span>
                            )}
                            {line.dstIp && (
                              <span>
                                dst{" "}
                                <span className="text-slate-300">
                                  {line.dstIp}
                                  {line.dstPort != null && `:${line.dstPort}`}
                                </span>
                              </span>
                            )}
                            {line.proto && (
                              <span>
                                proto{" "}
                                <span className="text-cyan-300">
                                  {line.proto}
                                </span>
                              </span>
                            )}
                            {line.mac && (
                              <span>
                                mac{" "}
                                <span className="text-slate-300">
                                  {line.mac}
                                </span>
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    </label>
                  );
                })}
              </div>
            )}
          </div>

          {totalPages > 1 && (
            <div className="px-4 py-3 border-t border-ink-700 bg-ink-850 flex justify-between items-center text-xs">
              <button
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={currentPage === 1}
                className="px-3 py-1.5 bg-ink-900 border border-ink-700 hover:border-cyan-500/40 disabled:opacity-40 disabled:cursor-not-allowed rounded-md text-slate-300"
              >
              ← {t("history_col_date")}
              </button>
              <span className="text-slate-400 font-mono">
                Página {currentPage} / {totalPages}
              </span>
              <button
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                disabled={currentPage === totalPages}
                className="px-3 py-1.5 bg-ink-900 border border-ink-700 hover:border-cyan-500/40 disabled:opacity-40 disabled:cursor-not-allowed rounded-md text-slate-300"
              >
                Siguiente →
              </button>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
