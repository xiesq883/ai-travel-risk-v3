import React from 'react';
import { AlertTriangle, Check, GitCompareArrows, Wand2 } from 'lucide-react';
import type {
  RiskInput,
  RiskLevel,
  RiskOptimizationProposal,
  RiskOptimizationResult,
  RiskReport,
} from '../../types/risk';

const levels: Record<RiskLevel, { label: string; className: string }> = {
  high: { label: '高风险', className: 'bg-red-50 text-red-800 border-red-200' },
  medium: { label: '需调整', className: 'bg-amber-50 text-amber-900 border-amber-200' },
  low: { label: '较低风险', className: 'bg-emerald-50 text-emerald-900 border-emerald-200' },
  unknown: { label: '待核实', className: 'bg-stone-100 text-stone-700 border-stone-300' },
};
const badge = (level: RiskLevel) => (
  <span className={`rounded-full border px-2 py-1 text-xs font-medium ${levels[level].className}`}>
    {levels[level].label}
  </span>
);
const displayValue = (value: number | string | null, unit: string) =>
  value == null ? '待补充' : `${value}${unit ? ` ${unit}` : ''}`;

const ProposalRow: React.FC<{ proposal: RiskOptimizationProposal }> = ({ proposal }) => (
  <li className="border-t border-stroke/70 py-3 first:border-t-0">
    <div className="flex flex-wrap items-center gap-2">
      {proposal.status === 'applied' ? (
        <Check size={15} className="text-emerald-700" aria-label="已应用到优化草稿" />
      ) : (
        <AlertTriangle size={15} className="text-amber-700" aria-label="需要确认" />
      )}
      <span className="font-medium">{proposal.title}</span>
      <span className="text-xs text-ink-muted">
        {proposal.status === 'applied' ? '草稿已调整' : '需要你确认'}
      </span>
    </div>
    <p className="mt-1 text-sm leading-relaxed text-ink-secondary">{proposal.reason}</p>
    <p className="mt-1 text-xs text-ink-muted">
      {proposal.field}：{displayValue(proposal.before, proposal.unit)}
      {proposal.status === 'applied' && <> → {displayValue(proposal.after, proposal.unit)}</>}
    </p>
  </li>
);

export const RiskOptimizationLoop: React.FC<{
  plan: RiskOptimizationResult;
  busy?: boolean;
  applied?: boolean;
  onApply: (input: RiskInput, report: RiskReport) => void;
}> = ({ plan, busy = false, applied = false, onApply }) => (
  <section className="space-y-4 border-y-2 border-accent/40 bg-accent/5 px-4 py-5" aria-label="方案优化闭环">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <div className="mb-2 flex items-center gap-2">
          <GitCompareArrows size={19} />
          <h2 className="text-lg font-semibold">方案优化闭环</h2>
        </div>
        <p className="text-sm leading-relaxed text-ink-secondary">原方案 → 找出风险 → 修改方案 → 再评估</p>
      </div>
      <div className="flex items-center gap-2 text-sm">
        <span>原方案</span>
        {badge(plan.before.overall_level)}
        <span aria-hidden="true">→</span>
        <span>优化草稿</span>
        {badge(plan.after.overall_level)}
      </div>
    </div>
    <p className="text-sm leading-relaxed">{plan.summary}</p>
    {plan.proposals.length > 0 ? (
      <ul className="rounded-card border border-stroke bg-white/60 px-4">
        {plan.proposals.map((proposal) => (
          <ProposalRow key={proposal.proposal_id} proposal={proposal} />
        ))}
      </ul>
    ) : (
      <p className="rounded-card border border-stroke bg-white/60 p-4 text-sm text-ink-secondary">
        当前规则没有找到可执行的调整项。可以继续补充资料，或直接重新评估。
      </p>
    )}
    <div className="flex flex-wrap items-center gap-3">
      <button
        type="button"
        className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        disabled={busy || applied || plan.applied_count === 0}
        onClick={() => onApply(plan.optimized_input, plan.after)}
      >
        <Wand2 size={15} />
        {applied ? '优化草稿已应用' : '应用优化草稿并更新评估'}
      </button>
      <p className="text-xs leading-relaxed text-ink-muted">
        预算、路线真实性和缺失资料不会被系统猜测；应用后结果会基于优化草稿重新评估，原方案仍保留在上方对比中。
      </p>
    </div>
  </section>
);
