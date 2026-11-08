type Props = {
  simulado?: boolean;
  exemplo_fixo?: boolean;
};

export function SimuladoBadge({ simulado = true, exemplo_fixo = false }: Props) {
  if (!simulado && !exemplo_fixo) return null;
  return (
    <span className="inline-flex items-center gap-2 rounded-full bg-amber-100 px-3 py-1 text-xs font-bold tracking-widest text-amber-900">
      {simulado && "SIMULADO"}
      {exemplo_fixo && <span className="normal-case tracking-normal">Exemplo fixo</span>}
    </span>
  );
}
