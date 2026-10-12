"use client";

import type { Periodo } from "@/lib/api-periodo";

export const OPCOES_PERIODO: { valor: Periodo; rotulo: string; dica: string }[] = [
  { valor: "mes", rotulo: "Mês atual", dica: "Títulos emitidos desde o dia 1 deste mês" },
  { valor: "6m", rotulo: "6 meses", dica: "Títulos emitidos nos últimos 6 meses, contando o atual" },
  { valor: "tudo", rotulo: "Tudo", dica: "Sem filtro de período (padrão)" },
];

/** Lê o período da URL. Valor ausente ou desconhecido = "tudo". */
export function lerPeriodo(valor: string | null | undefined): Periodo {
  return valor === "mes" || valor === "6m" ? valor : "tudo";
}

export default function PeriodoFiltro({
  valor,
  onChange,
  className = "",
}: {
  valor: Periodo;
  onChange: (p: Periodo) => void;
  className?: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Período"
      className={`inline-flex rounded-xl border border-line bg-panel p-1 ${className}`}
    >
      {OPCOES_PERIODO.map((o) => {
        const ativo = o.valor === valor;
        return (
          <button
            key={o.valor}
            type="button"
            role="radio"
            aria-checked={ativo}
            title={o.dica}
            onClick={() => onChange(o.valor)}
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
              ativo ? "bg-frost text-white shadow-soft" : "text-muted hover:text-ink"
            }`}
          >
            {o.rotulo}
          </button>
        );
      })}
    </div>
  );
}
