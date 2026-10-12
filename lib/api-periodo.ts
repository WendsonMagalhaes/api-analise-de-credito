/**
 * Chamadas da carteira com o filtro de período (mês atual | 6 meses | tudo).
 * Fica num arquivo próprio para não mexer no lib/api.ts inteiro: reaproveita
 * apiFetch e os tipos de lá.
 */
import { apiFetch, type Cliente, type DashboardParams, type DashboardResponse } from "@/lib/api";

export type Periodo = "mes" | "6m" | "tudo";

export type ClienteComPeriodo = Cliente & {
  maior_compra: number | null;
  maior_atraso_hoje: number | null;
};

export type Destaques = {
  maior_compra: { cliente: string; valor: number } | null;
  maior_atraso: { cliente: string; dias: number } | null;
};

export type DashboardPeriodoResponse = Omit<DashboardResponse, "clientes"> & {
  periodo: Periodo;
  destaques: Destaques;
  clientes: ClienteComPeriodo[];
};

export type DashboardPeriodoParams = DashboardParams & { periodo?: Periodo };

export async function fetchDashboardPeriodo(
  params: DashboardPeriodoParams = {},
  token?: string,
): Promise<DashboardPeriodoResponse> {
  const query = new URLSearchParams();
  query.set("pagina", String(params.pagina ?? 1));
  query.set("tamanho_pagina", String(params.tamanhoPagina ?? 25));
  if (params.busca) query.set("busca", params.busca);
  if (params.faixa && params.faixa !== "todas") query.set("faixa", params.faixa);
  if (params.ordenarPor) query.set("ordenar_por", params.ordenarPor);
  if (params.ordenarDir) query.set("ordenar_dir", params.ordenarDir);
  query.set("periodo", params.periodo ?? "tudo");

  const res = await apiFetch(`/api/dashboard?${query.toString()}`, { cache: "no-store" }, token);
  if (!res.ok) throw new Error("Falha ao buscar dashboard");
  return res.json();
}
