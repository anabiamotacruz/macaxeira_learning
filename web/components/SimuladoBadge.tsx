type Props = {
  simulado?: boolean;
  exemplo_fixo?: boolean;
};

export function SimuladoBadge({ simulado = true, exemplo_fixo = false }: Props) {
  if (!simulado && !exemplo_fixo) return null;
  return (
    <span className="cora-chip cora-chip-warn font-semibold tracking-wide" title="Dados sintéticos e integrações simuladas">
      {simulado && "SIMULADO"}
      {exemplo_fixo && <span className="normal-case tracking-normal">Exemplo fixo</span>}
    </span>
  );
}
