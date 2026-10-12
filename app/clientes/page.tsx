"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { exportCarteiraUrl, formatBRL } from "@/lib/api";
import {
  fetchDashboardPeriodo,
  type DashboardPeriodoResponse,
  type Periodo,
} from "@/lib/api-periodo";
import { PageHeader } from "@/components/ui/PageHeader";
import { IndicadorAtualizando, PaginaClientesSkeleton } from "@/components/ui/Skeleton";
import { StatCard } from "@/components/ui/StatCard";
import { SearchInput } from "@/components/ui/SearchInput";
import { FaixaBadge } from "@/components/ui/Badge";
import { TableShell, theadRowClass, thClass, tdClass, trClass, EmptyRow } from "@/components/ui/Table";
import PeriodoFiltro, { lerPeriodo } from "@/components/ui/PeriodoFiltro";
import InfoTip from "@/components/ui/InfoTip";
import { ArrowLeft, Download, ChevronLeft, ChevronRight, PackageOpen, TrendingUp, Clock } from "lucide-react";
import { formatDias, formatTendencia } from "@/lib/format";

const RECOMENDACAO_LABEL: Record<string, string> = {
  aumentar: "↑ Aumentar",
  reduzir: "↓ Reduzir",
  manter: "Manter",
  sem_dados: "—",
};

const RECOMENDACAO_COR: Record<string, string> = {
  aumentar: "text-verde",
  reduzir: "text-vermelho",
  manter: "text-muted",
  sem_dados: "text-muted",
};

type SortKey =
  | "score"
  | "valor_em_aberto"
  | "atraso_medio_dias"
  | "dias_vencido_max"
  | "margem_disponivel"
  | "margem_limite_atual";

// Direção "natural" de cada coluna: pra score, atraso etc. o mais
// interessante de ver primeiro é o pior caso; pra margem, o mais negativo
// (cliente já estourando o limite) é o mais urgente de revisar.
const DIRECAO_PADRAO: Record<SortKey, "asc" | "desc"> = {
  score: "asc",
  valor_em_aberto: "desc",
  atraso_medio_dias: "desc",
  dias_vencido_max: "desc",
  margem_disponivel: "asc",
  margem_limite_atual: "asc",
};

const TAMANHO_PAGINA = 25;
const NUM_COLUNAS = 15;

const PERIODO_ROTULO: Record<Periodo, string> = {
  mes: "no mês atual",
  "6m": "nos últimos 6 meses",
  tudo: "em todo o histórico",
};

const fmtNum = (v: number | null | undefined) => (v === null || v === undefined ? "—" : String(v));

function fmtAtrasoHoje(d: number | null) {
  if (d === null) return "—";
  return d > 0 ? `${d} dias` : "Em dia";
}

export default function ClientesPageWrapper() {
  return (
    <Suspense fallback={<PaginaClientesSkeleton />}>
      <ClientesPage />
    </Suspense>
  );
}

function ClientesPage() {
  const searchParams = useSearchParams();
  const faixaInicial = searchParams.get("faixa") || "todas";

  const [data, setData] = useState<DashboardPeriodoResponse | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  const [buscaInput, setBuscaInput] = useState("");
  const [busca, setBusca] = useState("");
  const [faixaFiltro, setFaixaFiltro] = useState<string>(faixaInicial);
  const [periodo, setPeriodo] = useState<Periodo>(lerPeriodo(searchParams.get("periodo")));
  const [sortKey, setSortKey] = useState<SortKey>("score");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [pagina, setPagina] = useState(1);

  // busca com debounce: espera parar de digitar antes de bater na API
  useEffect(() => {
    const t = setTimeout(() => {
      setBusca(buscaInput);
      setPagina(1);
    }, 400);
    return () => clearTimeout(t);
  }, [buscaInput]);

  useEffect(() => {
    // `ativo` descarta a resposta de uma busca antiga: digitando/ordenando
    // rápido, várias requisições ficam em voo e a mais lenta podia chegar por
    // último e sobrescrever o resultado da mais nova.
    let ativo = true;
    setCarregando(true);
    fetchDashboardPeriodo({
      pagina,
      tamanhoPagina: TAMANHO_PAGINA,
      busca,
      faixa: faixaFiltro,
      ordenarPor: sortKey,
      ordenarDir: sortDir,
      periodo,
    })
      .then((d) => {
        if (!ativo) return;
        setData(d);
        setErro(null);
      })
      .catch((e) => ativo && setErro(e.message))
      .finally(() => ativo && setCarregando(false));
    return () => {
      ativo = false;
    };
  }, [pagina, busca, faixaFiltro, sortKey, sortDir, periodo]);

  function mudarOrdenacao(key: SortKey) {
    setSortKey(key);
    setSortDir(DIRECAO_PADRAO[key]);
    setPagina(1);
  }

  function mudarFaixaFiltro(f: string) {
    setFaixaFiltro((atual) => (atual === f ? "todas" : f));
    setPagina(1);
  }

  function mudarPeriodo(p: Periodo) {
    setPeriodo(p);
    setPagina(1);
  }

  const semFiltroAtivo = !busca && faixaFiltro === "todas";

  if (erro) {
    return (
      <div className="border border-vermelho/30 bg-vermelhobg text-vermelho rounded-xl px-4 py-3 text-sm">
        Não consegui falar com a API ({erro}). Confirme que o backend está rodando em{" "}
        <code className="font-mono">http://localhost:8000</code>.
      </div>
    );
  }

  if (!data && carregando) {
    return <PaginaClientesSkeleton />;
  }

  if (!data) return null;

  if (data.total_clientes === 0 && semFiltroAtivo) {
    return (
      <div className="text-center py-24 border border-dashed border-line rounded-2xl bg-panel">
        <div className="w-14 h-14 rounded-2xl bg-frost/10 text-frost flex items-center justify-center mx-auto mb-4">
          <PackageOpen size={24} strokeWidth={2} />
        </div>
        <p className="text-ink text-lg font-medium mb-2">Nenhum dado importado ainda</p>
        <p className="text-muted text-sm mb-6">
          Suba os relatórios de contas a receber para começar a montar o histórico.
        </p>
        <Link
          href="/upload"
          className="inline-block bg-frost text-white px-5 py-2.5 rounded-xl text-sm font-semibold shadow-soft hover:bg-frostdark hover:shadow-glow active:scale-[0.98] transition-colors"
        >
          Atualizar relatórios
        </Link>
      </div>
    );
  }

  const { destaques } = data;

  return (
    <div>
      <PageHeader
        title="Clientes"
        subtitle={`${data.total_clientes} clientes no filtro atual${
          data.atualizado_em ? ` · atualizado em ${new Date(data.atualizado_em).toLocaleDateString("pt-BR")}` : ""
        }`}
        actions={
          <>
            <Link
              href="/dashboard"
              className="flex items-center gap-1.5 text-sm font-medium text-ink hover:text-frost border border-line rounded-xl px-3 py-2 transition-colors"
            >
              <ArrowLeft size={14} /> Dashboard
            </Link>
            <a
              href={exportCarteiraUrl}
              className="flex items-center gap-1.5 text-sm font-medium text-frost hover:text-frostdark border border-frost/30 rounded-xl px-3 py-2 transition-colors"
            >
              <Download size={14} /> Exportar Excel
            </a>
          </>
        }
      />

      {/* Filtro de período: afeta os destaques e as colunas de maior compra / atraso */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <PeriodoFiltro valor={periodo} onChange={mudarPeriodo} />
        <IndicadorAtualizando visivel={carregando} />
      </div>

      {/* Destaques do período */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-6">
        <StatCard
          label="Maior compra"
          value={destaques.maior_compra ? formatBRL(destaques.maior_compra.valor) : "—"}
          hint={
            destaques.maior_compra
              ? `${destaques.maior_compra.cliente} · ${PERIODO_ROTULO[periodo]}`
              : `sem títulos ${PERIODO_ROTULO[periodo]}`
          }
          icon={TrendingUp}
          accent="azul"
        />
        <StatCard
          label="Maior atraso hoje"
          value={destaques.maior_atraso ? `${destaques.maior_atraso.dias} dias` : "Em dia"}
          tone={destaques.maior_atraso ? "vermelho" : "neutro"}
          hint={
            destaques.maior_atraso
              ? `${destaques.maior_atraso.cliente} · ${PERIODO_ROTULO[periodo]}`
              : `nenhum título em atraso ${PERIODO_ROTULO[periodo]}`
          }
          icon={Clock}
        />
      </div>

      {/* Contagem por faixa — filtra a tabela ao clicar */}
      <div className="grid grid-cols-3 gap-3 mb-6">
        {(["verde", "amarelo", "vermelho"] as const).map((f) => (
          <button
            key={f}
            onClick={() => mudarFaixaFiltro(f)}
            className={`text-left rounded-2xl px-4 py-3 border shadow-soft transition-all ${
              faixaFiltro === f ? "border-frost ring-2 ring-frost/20" : "border-line hover:-translate-y-0.5"
            } ${f === "verde" ? "bg-verdebg text-verde" : f === "amarelo" ? "bg-amarelobg text-amarelo" : "bg-vermelhobg text-vermelho"}`}
          >
            <p className="text-xs uppercase tracking-wide opacity-80">{f}</p>
            <p className="text-xl font-semibold tabular mt-1">{data.resumo_geral.contagem_faixas[f] || 0}</p>
          </button>
        ))}
      </div>

      <div className="flex items-center gap-3 mb-4">
        <SearchInput value={buscaInput} onChange={setBuscaInput} placeholder="Buscar cliente…" className="flex-1" />
        <select
          value={sortKey}
          onChange={(e) => mudarOrdenacao(e.target.value as SortKey)}
          className="border border-line rounded-xl px-3 py-2 text-sm bg-panel text-ink placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-frost/30 focus:border-frost transition-colors"
        >
          <option value="score">Ordenar por score (pior primeiro)</option>
          <option value="valor_em_aberto">Ordenar por valor em aberto</option>
          <option value="atraso_medio_dias">Ordenar por atraso médio</option>
          <option value="dias_vencido_max">Ordenar por dias vencido</option>
          <option value="margem_limite_atual">Ordenar por margem s/ limite atual</option>
          <option value="margem_disponivel">Ordenar por margem s/ limite sugerido</option>
        </select>
      </div>

      <TableShell className={carregando ? "opacity-60 pointer-events-none transition-opacity" : "transition-opacity"}>
        <thead>
          <tr className={theadRowClass}>
            <th className={`${thClass} w-[260px]`}>Cliente</th>
            <th className={`${thClass} w-[90px]`}>
              <InfoTip chave="score">Score</InfoTip>
            </th>
            <th className={`${thClass} w-[80px]`}>
              <InfoTip chave="classe">Classe</InfoTip>
            </th>
            <th className={`${thClass} w-[130px]`}>
              <InfoTip chave="score_comportamento">Comp.</InfoTip>
              <span className="mx-1 text-muted">/</span>
              <InfoTip chave="score_exposicao">Exp.</InfoTip>
            </th>
            <th className={`${thClass} w-[110px]`}>Atraso médio</th>
            <th className={`${thClass} w-[110px]`}>Tendência</th>
            <th className={`${thClass} w-[130px]`}>Em aberto</th>
            <th className={`${thClass} w-[110px]`}>Dias vencido</th>
            <th className={`${thClass} w-[130px]`}>Limite atual</th>
            <th className={`${thClass} w-[140px]`}>
              <InfoTip chave="margem_atual">Margem s/ atual</InfoTip>
            </th>
            <th className={`${thClass} w-[130px]`}>Limite sugerido</th>
            <th className={`${thClass} w-[150px]`}>
              <InfoTip chave="margem_sugerido">Margem s/ sugerido</InfoTip>
            </th>
            <th className={`${thClass} w-[130px]`}>
              <InfoTip chave="maior_compra">Maior compra</InfoTip>
            </th>
            <th className={`${thClass} w-[130px]`}>
              <InfoTip chave="maior_atraso">Maior atraso hoje</InfoTip>
            </th>
            <th className={`${thClass} w-[120px]`}>Recomendação</th>
          </tr>
        </thead>
        <tbody>
          {data.clientes.length === 0 && <EmptyRow colSpan={NUM_COLUNAS}>Nenhum cliente encontrado com esse filtro.</EmptyRow>}
          {data.clientes.map((c) => (
            <tr key={c.cliente} className={trClass}>
              <td className={`${tdClass} whitespace-nowrap overflow-hidden text-ellipsis`} title={c.cliente}>
                <Link href={`/clientes/${encodeURIComponent(c.cliente)}`} className="text-ink font-medium hover:text-frost">
                  {c.cliente}
                </Link>
              </td>
              <td className={tdClass}>
                <FaixaBadge faixa={c.faixa} score={c.score} mostrarRotulo={false} />
              </td>
              <td className={`${tdClass} font-semibold`}>{c.classe_risco_5 ?? "—"}</td>
              <td className={`${tdClass} tabular`}>
                {fmtNum(c.score_comportamento)} / {fmtNum(c.score_exposicao)}
              </td>
              <td className={`${tdClass} tabular`}>{formatDias(c.atraso_medio_dias)}</td>
              <td className={`${tdClass} text-muted`}>{formatTendencia(c.tendencia)}</td>
              <td className={`${tdClass} tabular`}>{formatBRL(c.valor_em_aberto)}</td>
              <td className={`${tdClass} tabular`}>{c.dias_vencido_max > 0 ? formatDias(c.dias_vencido_max, 0) : "—"}</td>
              <td className={`${tdClass} tabular`}>{c.limite_atual === null ? "—" : formatBRL(c.limite_atual)}</td>
              <td
                className={`px-4 py-3 tabular font-medium ${
                  c.margem_limite_atual === null ? "text-muted" : c.margem_limite_atual >= 0 ? "text-verde" : "text-vermelho"
                }`}
              >
                {c.margem_limite_atual === null ? "—" : formatBRL(c.margem_limite_atual)}
              </td>
              <td className={`${tdClass} tabular`}>{c.limite_sugerido === null ? "—" : formatBRL(c.limite_sugerido)}</td>
              <td
                className={`px-4 py-3 tabular font-medium ${
                  c.margem_disponivel === null ? "text-muted" : c.margem_disponivel >= 0 ? "text-verde" : "text-vermelho"
                }`}
              >
                {c.margem_disponivel === null ? "—" : formatBRL(c.margem_disponivel)}
              </td>
              <td className={`${tdClass} tabular`}>{c.maior_compra === null ? "—" : formatBRL(c.maior_compra)}</td>
              <td
                className={`${tdClass} tabular ${c.maior_atraso_hoje && c.maior_atraso_hoje > 0 ? "text-vermelho" : ""}`}
              >
                {fmtAtrasoHoje(c.maior_atraso_hoje)}
              </td>
              <td className={`px-4 py-3 font-medium ${RECOMENDACAO_COR[c.recomendacao_limite]}`}>
                {RECOMENDACAO_LABEL[c.recomendacao_limite]}
              </td>
            </tr>
          ))}
        </tbody>
      </TableShell>

      <div className="flex items-center justify-between mt-4">
        <p className="text-xs text-muted">
          Página {data.pagina} de {data.total_paginas} · {data.total_clientes} clientes no filtro atual
        </p>
        <div className="flex gap-2">
          <button
            onClick={() => setPagina((p) => Math.max(1, p - 1))}
            disabled={data.pagina <= 1}
            className="flex items-center gap-1 text-sm border border-line rounded-xl px-3 py-1.5 disabled:opacity-40 hover:bg-panel2 transition-colors"
          >
            <ChevronLeft size={14} /> Anterior
          </button>
          <button
            onClick={() => setPagina((p) => Math.min(data.total_paginas, p + 1))}
            disabled={data.pagina >= data.total_paginas}
            className="flex items-center gap-1 text-sm border border-line rounded-xl px-3 py-1.5 disabled:opacity-40 hover:bg-panel2 transition-colors"
          >
            Próxima <ChevronRight size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
