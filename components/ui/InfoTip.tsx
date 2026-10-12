"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Info } from "lucide-react";

/** Explicações dos termos da tabela e dos cards. Texto em um lugar só. */
export const GLOSSARIO = {
  score: {
    titulo: "Score",
    texto: "Nota que resume o risco do cliente com base no histórico de pagamentos e no que ele deve hoje. Quanto mais alta, melhor a situação.",
  },
  classe: {
    titulo: "Classe",
    texto: "Classificação de risco de A (menor risco) a E (maior risco). Combina o comportamento de pagamento com a exposição atual.",
  },
  score_comportamento: {
    titulo: "Score comportamento",
    texto: "Nota só do jeito de pagar: atrasos, pontualidade e tendência do histórico.",
  },
  score_exposicao: {
    titulo: "Score exposição",
    texto: "Nota do tamanho da exposição: quanto o cliente deve hoje em relação ao limite e ao resto da carteira.",
  },
  margem_sugerido: {
    titulo: "Margem s/ limite sugerido",
    texto: "Limite sugerido menos o valor em aberto. Valor negativo significa que o cliente já passou do limite recomendado.",
  },
  margem_atual: {
    titulo: "Margem s/ limite atual",
    texto: "Limite cadastrado menos o valor em aberto. Valor negativo significa que o cliente está acima do limite cadastrado.",
  },
  maior_compra: {
    titulo: "Maior compra",
    texto: "Maior valor de um único título emitido para o cliente no período escolhido, somando títulos pagos e em aberto.",
  },
  maior_atraso: {
    titulo: "Maior atraso hoje",
    texto: "Maior número de dias em atraso, hoje, entre os títulos em aberto emitidos no período escolhido.",
  },
} as const;

export type ChaveGlossario = keyof typeof GLOSSARIO;

/** Ícone "i" que abre um balão com a explicação. Fecha com Esc ou clique fora. */
export default function InfoTip({ chave, children }: { chave: ChaveGlossario; children?: React.ReactNode }) {
  const [aberto, setAberto] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  const id = useId();
  const g = GLOSSARIO[chave];

  useEffect(() => {
    if (!aberto) return;
    function fora(e: MouseEvent) {
      if (!ref.current?.contains(e.target as Node)) setAberto(false);
    }
    function tecla(e: KeyboardEvent) {
      if (e.key === "Escape") setAberto(false);
    }
    document.addEventListener("mousedown", fora);
    document.addEventListener("keydown", tecla);
    return () => {
      document.removeEventListener("mousedown", fora);
      document.removeEventListener("keydown", tecla);
    };
  }, [aberto]);

  return (
    <span ref={ref} className="relative inline-flex items-center gap-1 align-middle">
      {children}
      <button
        type="button"
        aria-label={`O que é ${g.titulo}?`}
        aria-expanded={aberto}
        aria-controls={id}
        onClick={() => setAberto((v) => !v)}
        className="text-muted hover:text-frost"
      >
        <Info size={13} />
      </button>
      {aberto && (
        <span
          id={id}
          role="tooltip"
          className="absolute left-1/2 top-full z-30 mt-2 w-64 -translate-x-1/2 rounded-xl border border-line bg-panel p-3 text-left text-xs font-normal normal-case tracking-normal text-ink shadow-soft"
        >
          <span className="mb-1 block font-semibold">{g.titulo}</span>
          {g.texto}
        </span>
      )}
    </span>
  );
}
