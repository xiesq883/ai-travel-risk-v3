import React from 'react';
import type { RiskExplanation, RiskLevel } from '../../types/risk';

const levels: Record<RiskLevel, { text: string; style: string }> = {
  high: { text: '高风险', style: 'border-red-200 bg-red-50 text-red-900' },
  medium: { text: '需调整', style: 'border-amber-200 bg-amber-50 text-amber-900' },
  low: { text: '较低风险', style: 'border-emerald-200 bg-emerald-50 text-emerald-900' },
  unknown: { text: '待核实', style: 'border-stone-300 bg-stone-100 text-stone-800' },
};

const labels: Record<string, string> = {
  high: '高风险',
  medium: '需调整',
  low: '较低风险',
  unknown: '待核实',
  forecast: '逐日预报',
  seasonal_baseline: '季节参考',
  unavailable: '暂无资料',
  ready: '已核对',
  estimated: '仅估算',
  missing: '未查到',
};
const valueText = (value: number | string | boolean | null) =>
  value === null
    ? '未知 / 未提供'
    : typeof value === 'boolean'
      ? value
        ? '是'
        : '否'
      : typeof value === 'string'
        ? (labels[value] ?? value)
        : String(value);

const Step: React.FC<{ number: string; title: string; children: React.ReactNode }> = ({
  number,
  title,
  children,
}) => (
  <section className="min-w-0 rounded-card border border-stroke bg-surface/70 p-4">
    <h5 className="mb-3 flex items-center gap-2 text-sm font-semibold">
      <span
        aria-hidden="true"
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-stroke text-xs text-ink-muted"
      >
        {number}
      </span>
      {title}
    </h5>
    {children}
  </section>
);

export const RiskExplanationChain: React.FC<{
  explanation: RiskExplanation;
  suggestion?: string;
}> = ({ explanation, suggestion }) => {
  const badge = levels[explanation.risk_level];
  return (
    <div
      className="mt-3 grid min-w-0 gap-3 text-sm leading-relaxed sm:grid-cols-2 xl:grid-cols-4"
      aria-label="数据 → 计算 → 风险 → 解释"
    >
      <Step number="1" title="数据">
        <dl className="space-y-2 break-words">
          {explanation.data.slice(0, 4).map((item, index) => (
            <div key={index}>
              <dt className="text-xs text-ink-muted">{item.label}</dt>
              <dd className="font-medium">
                {valueText(item.value)}
                {item.value !== null && item.unit ? ` ${item.unit}` : ''}
              </dd>
            </div>
          ))}
        </dl>
        <details className="mt-3 border-t border-stroke pt-2">
          <summary className="min-h-8 cursor-pointer text-xs text-accent">
            全部 {explanation.data.length} 项数据、来源与字段
          </summary>
          <ul className="mt-2 space-y-3 break-words text-xs text-ink-secondary">
            {explanation.data.map((item, index) => (
              <li key={index}>
                <p>
                  {item.label}：{valueText(item.value)} {item.value !== null ? item.unit : ''}
                </p>
                <p>来源：{item.source_label}</p>
                {item.observed_at && <p>采集时间：{item.observed_at}</p>}
                {item.source_ids.length > 0 && (
                  <p className="break-all">来源 ID：{item.source_ids.join('、')}</p>
                )}
                <code className="break-all text-[10px] text-ink-muted">{item.field}</code>
              </li>
            ))}
          </ul>
        </details>
      </Step>
      <Step number="2" title="计算">
        <ol className="space-y-3 break-words">
          {explanation.calculation.slice(0, 4).map((calculation, index) => (
            <li key={index}>
              <p className="text-xs text-ink-secondary">{calculation.expression}</p>
              <p className="mt-1 font-medium">
                = {valueText(calculation.result)}
                {calculation.result !== null && calculation.unit ? ` ${calculation.unit}` : ''}
              </p>
            </li>
          ))}
        </ol>
        {explanation.calculation.length > 4 && (
          <details className="mt-3 border-t border-stroke pt-2">
            <summary className="min-h-8 cursor-pointer text-xs text-accent">
              展开其余 {explanation.calculation.length - 4} 步计算
            </summary>
            <ol start={5} className="mt-2 space-y-3 break-words">
              {explanation.calculation.slice(4).map((calculation, index) => (
                <li key={index}>
                  <p className="text-xs text-ink-secondary">{calculation.expression}</p>
                  <p className="mt-1 font-medium">
                    = {valueText(calculation.result)}
                    {calculation.result !== null && calculation.unit ? ` ${calculation.unit}` : ''}
                  </p>
                </li>
              ))}
            </ol>
          </details>
        )}
      </Step>
      <Step number="3" title="风险">
        <span
          className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${badge.style}`}
        >
          {badge.text}
        </span>
        <p className="mt-3 break-words text-xs text-ink-secondary">{explanation.rule}</p>
      </Step>
      <Step number="4" title="解释">
        <p className="break-words text-ink-secondary">{explanation.explanation}</p>
        {suggestion && <p className="mt-3 border-t border-stroke pt-3">建议：{suggestion}</p>}
      </Step>
    </div>
  );
};
