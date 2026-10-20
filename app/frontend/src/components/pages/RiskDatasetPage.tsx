import React, { useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  CloudRain,
  Coins,
  FileJson,
  Footprints,
  Route,
  Upload,
} from 'lucide-react';
import { api } from '../../lib/api';
import { useApp } from '../../context/AppContext';
import { PageShell } from '../ui/PageShell';
import { RiskOptimizationLoop } from '../risk/RiskOptimizationLoop';
import type { TripRunResponse } from '../../types/api';
import type {
  DatasetDay,
  DatasetImportResponse,
  DatasetRiskReview,
  DatasetRoute,
  RiskDimension,
  RiskInput,
  RiskLevel,
  RiskOptimizationResult,
} from '../../types/risk';

const dimensions = [
  { key: 'weather', label: '天气', icon: CloudRain, description: '户外安排会不会受影响' },
  { key: 'budget', label: '预算', icon: Coins, description: '整趟花费有没有余量' },
  { key: 'transport', label: '交通', icon: Route, description: '路线和衔接能不能成立' },
  { key: 'fatigue', label: '体力', icon: Footprints, description: '每天的强度能否接受' },
] as const;

const levels: Record<RiskLevel, { label: string; className: string }> = {
  high: { label: '高风险', className: 'bg-red-50 text-red-800 border-red-200' },
  medium: { label: '需调整', className: 'bg-amber-50 text-amber-900 border-amber-200' },
  low: { label: '较低风险', className: 'bg-emerald-50 text-emerald-900 border-emerald-200' },
  unknown: { label: '待核实', className: 'bg-stone-100 text-stone-700 border-stone-300' },
};

const buttonClass =
  'inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-stroke px-4 py-2 text-sm font-medium text-ink hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-50';
const inputClass =
  'min-h-11 w-full border-b border-stroke bg-transparent px-1 py-2 text-[15px] text-ink outline-none focus:border-accent disabled:opacity-50';
const badgeClass = 'inline-flex items-center rounded border px-2 py-0.5 text-[11px] font-medium';

const MODE_LABEL: Record<string, string> = {
  flight: '飞机',
  high_speed_rail: '高铁',
  train: '火车',
  coach: '大巴',
  ferry: '轮渡',
  metro: '地铁',
  bus: '公交',
  tram: '有轨电车',
  taxi: '出租车',
  ride_hailing: '网约车',
  drive: '自驾',
  bike: '骑行',
  walk: '步行',
  other: '其他',
  unknown: '方式未知',
};

const MEAL_LABEL: Record<string, string> = {
  breakfast: '早餐',
  lunch: '午餐',
  dinner: '晚餐',
  snack: '加餐',
  other: '其他餐次',
};

const money = (value: number | null | undefined) =>
  value == null ? '未知' : `¥${value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`;

const range = (low: number | null, high: number | null, point: number | null) => {
  if (low != null && high != null && Math.abs(high - low) > 0.009) {
    return `¥${low.toLocaleString('zh-CN')}–¥${high.toLocaleString('zh-CN')}`;
  }
  return money(point ?? low ?? high);
};

const minutes = (value: number | null | undefined) => {
  if (value == null) return '未知';
  if (value < 60) return `${Math.round(value)} 分钟`;
  const hours = Math.floor(value / 60);
  const rest = Math.round(value % 60);
  return rest ? `${hours} 小时 ${rest} 分` : `${hours} 小时`;
};

const priceLabel: Record<string, string> = {
  actual_quote: '实际报价',
  estimated: '参考估算',
  unknown: '金额未知',
};

const confidenceLabel: Record<string, string> = {
  verified: '来源已核验',
  estimated: '程序估算',
  unverified: '来源未核验',
  unknown: '无来源',
};

const CoverageBadge: React.FC<{ value: string }> = ({ value }) => {
  const map: Record<string, string> = {
    complete: '数据完整',
    partial: '部分数据',
    missing: '数据不足',
    verified: '已核实',
    estimated: '估算',
    none_required: '无需交通',
    unknown: '未说明',
  };
  const tone =
    value === 'complete' || value === 'verified' || value === 'none_required'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
      : value === 'missing' || value === 'unknown'
        ? 'border-stone-300 bg-stone-100 text-stone-700'
        : 'border-amber-200 bg-amber-50 text-amber-900';
  return <span className={`${badgeClass} ${tone}`}>{map[value] ?? value}</span>;
};

const LevelBadge: React.FC<{ level: RiskLevel }> = ({ level }) => (
  <span className={`${badgeClass} ${levels[level].className}`}>{levels[level].label}</span>
);

const Field: React.FC<{ label: string; children: React.ReactNode; hint?: string }> = ({
  label,
  children,
  hint,
}) => (
  <label className="block">
    <span className="mb-1 block text-xs font-medium text-ink-secondary">{label}</span>
    {children}
    {hint && <span className="mt-1 block text-[11px] leading-relaxed text-ink-muted">{hint}</span>}
  </label>
);

const routeState = (route: DatasetRoute) => {
  if (route.route_status === 'missing') return { label: '未查到', tone: 'border-stone-300 bg-stone-100 text-stone-700' };
  if (route.route_status === 'ready' && route.confidence === 'verified') {
    return { label: '已核实', tone: 'border-emerald-200 bg-emerald-50 text-emerald-900' };
  }
  return { label: '估算', tone: 'border-amber-200 bg-amber-50 text-amber-900' };
};

const SourceLinks: React.FC<{
  ids: string[];
  lookup: Map<string, DatasetImportResponse['dataset']['sources'][number]>;
}> = ({ ids, lookup }) => {
  if (!ids.length) return <span className="text-xs text-ink-muted">无来源记录</span>;
  return (
    <div className="flex flex-wrap gap-2">
      {ids.map((id) => {
        const source = lookup.get(id);
        if (!source) return null;
        const label = `${source.title || source.provider || id} · ${confidenceLabel[source.confidence]}`;
        return source.url ? (
          <a
            key={id}
            href={source.url}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-accent underline"
          >
            {label}
          </a>
        ) : (
          <span key={id} className="text-xs text-ink-muted">
            {label}
          </span>
        );
      })}
    </div>
  );
};

const DayCard: React.FC<{
  day: DatasetDay;
  dataset: DatasetImportResponse['dataset'];
  sources: Map<string, DatasetImportResponse['dataset']['sources'][number]>;
}> = ({ day, dataset, sources }) => {
  const estimated = new Set(day.metrics.estimated_fields);
  const lodging = dataset.lodgings.find((item) => item.stay_id === day.lodging_stay_id);
  const plannedMeals = day.meals.filter((meal) => meal.status === 'planned');
  const missingMeals = day.meals.filter((meal) => meal.status === 'not_planned');
  const weather = day.weather;
  return (
    <details className="group rounded-lg border border-stroke bg-panel" open={day.day_index === 1}>
      <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-3 p-4">
        <div className="flex min-w-0 items-center gap-3">
          <span className="text-xs tabular-nums text-ink-muted">D{day.day_index}</span>
          <div className="min-w-0">
            <p className="truncate font-semibold text-ink">
              {day.date} · {day.destination_name || day.destination_id}
            </p>
            <p className="truncate text-xs text-ink-muted">
              {day.start_place?.name ?? '起点未知'} → {day.end_place?.name ?? '终点未知'}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-ink-secondary">
          <span>
            步行 {day.metrics.walking_km == null ? '未知' : `${day.metrics.walking_km.toFixed(1)} km`}
            {estimated.has('walking_km') && ' · 估算'}
          </span>
          <span>活动 {minutes(day.metrics.activity_minutes)}</span>
          <span>交通 {minutes(day.metrics.transport_minutes)}</span>
          <span>
            休息 {minutes(day.metrics.rest_minutes)}
            {estimated.has('rest_minutes') && ' · 估算'}
          </span>
          <ChevronDown size={16} className="transition group-open:rotate-180" />
        </div>
      </summary>
      <div className="space-y-5 border-t border-stroke p-4">
        <section>
          <h3 className="mb-2 text-sm font-semibold text-ink">路线与衔接</h3>
          {day.routes.length ? (
            <ul className="space-y-2">
              {day.routes.map((route) => {
                const state = routeState(route);
                return (
                  <li key={route.route_id} className="rounded border border-stroke/70 p-3 text-sm">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-medium text-ink">
                        {MODE_LABEL[route.mode] ?? route.mode} · {route.from_endpoint.name} →{' '}
                        {route.to_endpoint.name}
                      </span>
                      <span className={`${badgeClass} ${state.tone}`}>{state.label}</span>
                    </div>
                    <p className="mt-1 text-xs text-ink-secondary">
                      时长 {minutes(route.duration_minutes)} · 距离{' '}
                      {route.distance_m == null ? '未知' : `${(route.distance_m / 1000).toFixed(1)} km`}
                      {route.distance_source === 'program_estimate' && '（程序估算）'}
                      {route.fare_cny != null && ` · ${money(route.fare_cny)}`}
                      {route.transfer_count > 0 && ` · 换乘 ${route.transfer_count} 次`}
                    </p>
                    {route.steps.length > 0 && (
                      <p className="mt-1 text-xs text-ink-muted">
                        {route.steps
                          .map(
                            (step) =>
                              `${step.service_number || step.line_name || MODE_LABEL[step.mode] || step.mode} ${step.from_name}→${step.to_name}`
                          )
                          .join(' / ')}
                      </p>
                    )}
                    <div className="mt-2">
                      <SourceLinks ids={route.source_ids} lookup={sources} />
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="text-sm text-ink-muted">当天没有登记交通段。</p>
          )}
        </section>

        <section>
          <h3 className="mb-2 text-sm font-semibold text-ink">餐饮</h3>
          <ul className="space-y-2">
            {plannedMeals.map((meal) => (
              <li key={meal.meal_id} className="rounded border border-stroke/70 p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium">
                    {MEAL_LABEL[meal.meal_type] ?? meal.meal_type} ·{' '}
                    {meal.restaurant_name ?? '餐厅待确认'}
                  </span>
                  <span className={`${badgeClass} border-stroke bg-stone-50 text-ink-secondary`}>
                    {priceLabel[meal.price_type]}
                  </span>
                </div>
                <p className="mt-1 text-xs text-ink-secondary">
                  人均 {money(meal.per_person_cny)} · 用餐人数 {meal.party_size ?? '未知'} · 合计{' '}
                  {money(meal.total_cny)}
                </p>
                {meal.address && <p className="mt-1 text-xs text-ink-muted">{meal.address}</p>}
                <div className="mt-2">
                  <SourceLinks ids={meal.source_ids} lookup={sources} />
                </div>
              </li>
            ))}
            {missingMeals.map((meal) => (
              <li key={meal.meal_id} className="text-xs text-ink-muted">
                {MEAL_LABEL[meal.meal_type] ?? meal.meal_type}：行程未安排，费用保持未知。
              </li>
            ))}
          </ul>
        </section>

        {lodging && (
          <section>
            <h3 className="mb-2 text-sm font-semibold text-ink">住宿</h3>
            <div className="rounded border border-stroke/70 p-3 text-sm">
              <p className="font-medium">
                {lodging.name} · {lodging.nights} 晚
              </p>
              <p className="mt-1 text-xs text-ink-secondary">
                {lodging.check_in_date} → {lodging.check_out_date} · 每晚 {money(lodging.nightly_cny)} · 合计{' '}
                {money(lodging.total_cny)}
              </p>
              <p className="mt-1 text-xs text-ink-muted">
                {priceLabel[lodging.price_type]} ·{' '}
                {lodging.availability_status === 'confirmed' ? '已确认有房' : '未确认房态'} · 房间数{' '}
                {lodging.room_count ?? '未知'}
              </p>
              <div className="mt-2">
                <SourceLinks ids={lodging.source_ids} lookup={sources} />
              </div>
            </div>
          </section>
        )}

        <section>
          <h3 className="mb-2 text-sm font-semibold text-ink">活动与体力</h3>
          <ul className="space-y-2">
            {day.activities.map((activity) => (
              <li key={activity.activity_id} className="rounded border border-stroke/70 p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium">{activity.name}</span>
                  <span className="text-xs text-ink-muted">
                    {minutes(activity.duration_minutes)} · 门票 {money(activity.ticket_cny)}
                  </span>
                </div>
                {activity.start_at && (
                  <p className="mt-1 text-xs text-ink-secondary">
                    {activity.start_at.slice(11, 16)}–{activity.end_at?.slice(11, 16) ?? '未知'}
                  </p>
                )}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-ink-secondary">
            户外 {minutes(day.metrics.outdoor_minutes)}
            {estimated.has('outdoor_minutes') && '（程序估算）'} · 换乘 {day.metrics.transfers} 次
          </p>
        </section>

        <section>
          <h3 className="mb-2 text-sm font-semibold text-ink">天气</h3>
          {weather ? (
            <p className="text-sm text-ink-secondary">
              {weather.condition_label ?? '天气现象未知'} · {weather.low_c ?? '?'}–{weather.high_c ?? '?'}℃ ·
              降水 {weather.precipitation_mm ?? '未知'} mm（{weather.precipitation_probability_pct ?? '未知'}%）·
              采集 {weather.retrieved_at ? new Date(weather.retrieved_at).toLocaleString('zh-CN') : '时间未知'} ·{' '}
              {confidenceLabel[weather.confidence]}
            </p>
          ) : (
            <p className="text-sm text-ink-muted">未取得这一天可用的天气快照。</p>
          )}
          {day.warnings.length > 0 && (
            <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-ink-secondary">
              {day.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
        </section>

        {(day.assumptions.length > 0 ||
          day.routes.some((route) => route.assumptions.length > 0)) && (
          <details>
            <summary className="cursor-pointer text-xs text-ink-muted">估算方法与假设</summary>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-ink-secondary">
              {[
                ...day.assumptions.map((item) => item.text),
                ...day.routes.flatMap((route) => route.assumptions.map((item) => item.text)),
              ]
                .filter((text, index, rows) => rows.indexOf(text) === index)
                .map((text) => (
                  <li key={text}>{text}</li>
                ))}
            </ul>
          </details>
        )}
      </div>
    </details>
  );
};

const DimensionCard: React.FC<{ dimension: RiskDimension }> = ({ dimension }) => (
  <article className="rounded-lg border border-stroke bg-panel p-4">
    <div className="flex items-center justify-between gap-3">
      <h3 className="font-semibold text-ink">{dimension.label}</h3>
      <LevelBadge level={dimension.level} />
    </div>
    <p className="mt-2 text-sm text-ink-secondary">{dimension.summary}</p>
    <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-ink-muted">
      <CoverageBadge value={dimension.coverage} />
      {dimension.estimated_data.length > 0 && (
        <span className={`${badgeClass} border-amber-200 bg-amber-50 text-amber-900`}>
          含 {dimension.estimated_data.length} 项估算
        </span>
      )}
    </div>
    {dimension.findings.length > 0 && (
      <ul className="mt-3 space-y-3">
        {dimension.findings.map((finding) => (
          <li key={finding.rule_id + finding.title} className="rounded border border-stroke/70 p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium text-ink">{finding.title}</p>
              <LevelBadge level={finding.level} />
            </div>
            <p className="mt-1 text-xs leading-relaxed text-ink-secondary">{finding.reason}</p>
            <p className="mt-1 text-xs leading-relaxed text-ink-secondary">
              建议：{finding.suggestion}
            </p>
            <details className="mt-2">
              <summary className="cursor-pointer text-[11px] text-ink-muted">查看计算依据</summary>
              <ul className="mt-2 space-y-1 text-[11px] text-ink-muted">
                {finding.explanation.data.slice(0, 8).map((row) => (
                  <li key={row.field}>
                    {row.label}：{row.value == null ? '未知' : String(row.value)}
                    {row.unit} · {row.source_label}
                  </li>
                ))}
                {finding.explanation.calculation.map((row) => (
                  <li key={row.expression}>
                    {row.expression} = {row.result == null ? '未知' : String(row.result)}
                    {row.unit}
                  </li>
                ))}
              </ul>
            </details>
          </li>
        ))}
      </ul>
    )}
    {dimension.missing_data.length > 0 && (
      <details className="mt-3">
        <summary className="cursor-pointer text-xs text-ink-muted">
          待补充 {dimension.missing_data.length} 项
        </summary>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-ink-secondary">
          {dimension.missing_data.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </details>
    )}
    {dimension.estimated_data.length > 0 && (
      <details className="mt-2">
        <summary className="cursor-pointer text-xs text-ink-muted">
          估算依据 {dimension.estimated_data.length} 项
        </summary>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-ink-secondary">
          {dimension.estimated_data.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </details>
    )}
  </article>
);

export const RiskDatasetPage: React.FC = () => {
  const { state } = useApp();
  const [runs, setRuns] = useState<TripRunResponse[]>([]);
  const [selectedRun, setSelectedRun] = useState(state.currentTripRunId ?? '');
  const [imported, setImported] = useState<DatasetImportResponse | null>(null);
  const [review, setReview] = useState<DatasetRiskReview | null>(null);
  const [budget, setBudget] = useState<number | null>(null);
  const [limits, setLimits] = useState<RiskInput['limits'] | null>(null);
  const [optimization, setOptimization] = useState<RiskOptimizationResult | null>(null);
  const [optimizationApplied, setOptimizationApplied] = useState(false);
  const [sourceKind, setSourceKind] = useState<'run' | 'file'>('run');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [isDemo, setIsDemo] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    api
      .listTripRuns({ mode: 'deep', limit: 80 })
      .then((result) => {
        if (active) setRuns(result.runs);
      })
      .catch(() => {
        if (active) setError('暂时无法读取已有行程，可以改为导入导出的 JSON 文件。');
      });
    return () => {
      active = false;
    };
  }, []);

  const importRun = async (runId: string) => {
    if (!runId) return;
    setBusy(true);
    setError('');
    setOptimization(null);
    setOptimizationApplied(false);
    setReview(null);
    try {
      const result = await api.importTripDataset(runId);
      setImported(result);
      setLimits(result.input.limits);
      setSourceKind('run');
      setIsDemo(/示例|演示|demo|sample/i.test(result.dataset.trip.title));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '导入行程失败，请稍后重试。');
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (state.currentTripRunId && !imported) {
      void importRun(state.currentTripRunId);
    }
    // Import once for the current run; later selection is explicit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.currentTripRunId]);

  const loadFile = async (file: File) => {
    setBusy(true);
    setError('');
    setOptimization(null);
    setOptimizationApplied(false);
    setReview(null);
    try {
      const payload = JSON.parse(await file.text()) as { schema_version?: string };
      if (payload.schema_version !== 'trip-dataset.v1') {
        throw new Error('文件不是 trip-dataset.v1 结构化行程。');
      }
      const result = await api.inspectImportedDataset(payload as never);
      setImported(result);
      setLimits(result.input.limits);
      setSelectedRun('');
      setSourceKind('file');
      setIsDemo(/示例|演示|demo|sample/i.test(file.name + result.dataset.trip.title));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '读取文件失败。');
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const loadExample = async () => {
    setBusy(true);
    setError('');
    setReview(null);
    try {
      const dataset = await api.getDatasetExample();
      const result = await api.inspectImportedDataset(dataset);
      setImported(result);
      setLimits(result.input.limits);
      setSelectedRun('');
      setSourceKind('file');
      setIsDemo(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '载入示例失败。');
    } finally {
      setBusy(false);
    }
  };

  const assess = async () => {
    if (!imported) return;
    if (budget == null || budget <= 0) {
      setError('请填写整趟旅行、全部同行人的总预算上限。');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const result =
        sourceKind === 'run' && selectedRun
          ? await api.assessTripDataset(selectedRun, {
              budget_cap_cny: budget,
              limits: limits ?? undefined,
            })
          : await api.assessImportedDataset(imported.dataset, budget);
      setReview(result);
      setOptimization(null);
      setOptimizationApplied(false);
      requestAnimationFrame(() => resultRef.current?.scrollIntoView({ behavior: 'smooth' }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '评估失败，请稍后重试。');
    } finally {
      setBusy(false);
    }
  };

  const optimize = async () => {
    if (!review) return;
    setBusy(true);
    setError('');
    try {
      const result = await api.optimizeTravelRisk(review.input, {
        inputOrigin: 'journeypilot',
        bundleId: review.assessment.bundle_id,
      });
      const useful = result.proposals.filter(
        (proposal) => proposal.field !== 'missing_data' || proposal.status === 'applied'
      );
      setOptimization({ ...result, proposals: useful });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '生成优化草稿失败。');
    } finally {
      setBusy(false);
    }
  };

  const applyOptimization = (nextInput: RiskInput, nextReport: DatasetRiskReview['assessment']) => {
    if (!review) return;
    setReview({ ...review, input: nextInput, assessment: nextReport });
    setOptimizationApplied(true);
  };

  const dataset = imported?.dataset;
  const summary = imported?.import_summary;
  const sourceLookup = new Map((dataset?.sources ?? []).map((source) => [source.citation_id, source]));
  const criticalMissing = review
    ? review.assessment.dimensions
        .filter((dimension) => dimension.level === 'unknown' || dimension.coverage !== 'complete')
        .flatMap((dimension) => dimension.missing_data.map((item) => `${dimension.label}：${item}`))
    : [];

  return (
    <PageShell
      title="风险评估"
      purpose="导入生成旅途的结构化结果，只填写整趟预算，就能看清四项风险。"
      state={{ kind: 'ready' }}
    >
      <div className="space-y-7 p-4 sm:p-6">
        {isDemo && (
          <div role="note" className="border-l-4 border-amber-500 bg-amber-50 p-4 text-sm text-amber-950">
            当前为演示数据：路线、餐饮、住宿和价格均为测试样例，不代表真实报价或可用库存。
          </div>
        )}
        <section className="space-y-3 border-y border-stroke py-5" aria-label="导入结构化行程">
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-[240px] flex-1 basis-full sm:basis-0">
              <Field label="导入生成旅途的结构化结果">
                <select
                  className={inputClass}
                  value={selectedRun}
                  disabled={busy}
                  onChange={(event) => setSelectedRun(event.target.value)}
                >
                  <option value="">选择一趟已完成的行程</option>
                  {state.currentTripRunId &&
                    !runs.some((run) => run.run_id === state.currentTripRunId) && (
                      <option value={state.currentTripRunId}>当前行程</option>
                    )}
                  {runs.map((run) => (
                    <option value={run.run_id} key={run.run_id}>
                      {run.title ?? '未命名行程'}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <button
              className={buttonClass}
              disabled={busy || !selectedRun}
              onClick={() => void importRun(selectedRun)}
            >
              <FileJson size={16} /> 导入并查看
            </button>
            <button className={buttonClass} disabled={busy} onClick={() => fileRef.current?.click()}>
              <Upload size={16} /> 导入 JSON 文件
            </button>
            <button className={buttonClass} disabled={busy} onClick={() => void loadExample()}>
              载入演示数据
            </button>
            <input
              ref={fileRef}
              type="file"
              accept="application/json,.json"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void loadFile(file);
              }}
            />
          </div>
          {error && <p className="text-sm text-red-800">{error}</p>}
        </section>

        {imported && dataset && summary && (
          <>
            <section className="rounded-lg border border-stroke bg-panel p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <CheckCircle2 size={18} className="text-emerald-700" />
                    <h2 className="text-lg font-semibold text-ink">已自动读取行程</h2>
                    <span className="rounded border border-stroke px-2 py-0.5 text-[11px] text-ink-muted">
                      {dataset.schema_version}
                    </span>
                  </div>
                  <p className="mt-2 text-sm text-ink-secondary">
                    {dataset.trip.title} · {summary.day_count} 天 ·{' '}
                    {summary.destinations.join('、') || '目的地未命名'} · {dataset.trip.start_date} 至{' '}
                    {dataset.trip.end_date}
                  </p>
                  <p className="mt-1 text-[11px] text-ink-muted">
                    Bundle {dataset.trip.bundle_id} · 数据集 {dataset.dataset_id} · 同行{' '}
                    {dataset.trip.party.adults + dataset.trip.party.children} 人
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-xs text-ink-muted">系统计算的预计总费用</p>
                  <p className="text-2xl font-semibold text-ink">
                    {range(summary.estimated_total.low_cny, summary.estimated_total.high_cny, summary.estimated_total.point_cny)}
                  </p>
                  <div className="mt-1 flex justify-end gap-2">
                    <CoverageBadge value={summary.cost_coverage} />
                    {summary.unknown_cost_count > 0 && (
                      <span className={`${badgeClass} border-amber-200 bg-amber-50 text-amber-900`}>
                        {summary.unknown_cost_count} 项金额未知
                      </span>
                    )}
                  </div>
                </div>
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                <div className="rounded border border-stroke/70 p-3">
                  <p className="text-xs text-ink-muted">费用明细</p>
                  <p className="mt-1 text-sm text-ink">
                    {summary.priced_cost_count} 项有金额 · {summary.unknown_cost_count} 项未知
                  </p>
                </div>
                <div className="rounded border border-stroke/70 p-3">
                  <p className="text-xs text-ink-muted">可追溯来源</p>
                  <p className="mt-1 text-sm text-ink">{summary.source_count} 条</p>
                </div>
                <div className="rounded border border-stroke/70 p-3">
                  <p className="text-xs text-ink-muted">估算字段</p>
                  <p className="mt-1 text-sm text-ink">{summary.estimated_fields.length} 项</p>
                </div>
              </div>
            </section>

            <section className="rounded-lg border border-stroke bg-panel p-5" aria-label="预算与评估">
              <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
                <Field
                  label="总预算上限（元）"
                  hint="全部同行人、整趟旅行。预计总费用由系统按导入明细计算，不需要逐项填写。"
                >
                  <input
                    type="number"
                    min={0.01}
                    step={100}
                    className={inputClass}
                    value={budget ?? ''}
                    disabled={busy}
                    placeholder="例如 6000"
                    onChange={(event) =>
                      setBudget(event.target.value === '' ? null : Number(event.target.value))
                    }
                  />
                </Field>
                <button className={buttonClass} disabled={busy} onClick={() => void assess()}>
                  开始风险评估 <ArrowRight size={16} />
                </button>
              </div>
              <details className="mt-3">
                <summary className="cursor-pointer text-xs text-ink-muted">调整每日强度偏好（可选）</summary>
                <div className="mt-3 grid gap-3 sm:grid-cols-3">
                  {(
                    [
                      ['max_daily_walking_km', '最多步行（km/天）'],
                      ['max_daily_active_hours', '最多活动加交通（小时/天）'],
                      ['min_daily_rest_minutes', '至少专门休息（分钟/天）'],
                    ] as const
                  ).map(([key, label]) => (
                    <Field key={key} label={label}>
                      <input
                        type="number"
                        min={0}
                        className={inputClass}
                        value={limits?.[key] ?? ''}
                        disabled={busy}
                        onChange={(event) =>
                          setLimits((current) => ({
                            ...(current ?? imported.input.limits),
                            [key]: Number(event.target.value),
                          }))
                        }
                      />
                    </Field>
                  ))}
                </div>
              </details>
            </section>

            <section className="space-y-3" aria-label="逐日导入明细">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-ink">自动读取的逐日明细</h2>
                <span className="text-xs text-ink-muted">展开可查看路线、餐次、住宿与来源</span>
              </div>
              {dataset.days.map((day) => (
                <DayCard key={day.day_id} day={day} dataset={dataset} sources={sourceLookup} />
              ))}
            </section>

            <details className="rounded-lg border border-stroke bg-panel p-4">
              <summary className="cursor-pointer text-sm font-medium text-ink">
                外部数据源状态与导入说明
              </summary>
              <ul className="mt-3 space-y-2 text-xs text-ink-secondary">
                {dataset.data_sources
                  .filter((source) => ['weather', 'route', 'search', 'hotel'].includes(source.kind))
                  .map((source) => (
                    <li key={source.source_id}>
                      {source.configured ? '已配置' : '未配置'} · {source.name}：{source.note}
                    </li>
                  ))}
                {summary.warnings.map((warning) => (
                  <li key={warning} className="text-amber-900">
                    {warning}
                  </li>
                ))}
              </ul>
            </details>
          </>
        )}

        {review && (
          <div ref={resultRef} className="space-y-4 border-t border-stroke pt-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-ink">评估结果</h2>
                <p className="mt-1 text-sm text-ink-secondary">{review.assessment.summary}</p>
              </div>
              <div className="flex items-center gap-2">
                <button className={buttonClass} disabled={busy} onClick={() => void optimize()}>
                  生成优化草稿
                </button>
                <span className="text-xs text-ink-muted">综合</span>
                <LevelBadge level={review.assessment.overall_level} />
              </div>
            </div>
            {optimization && (
              <RiskOptimizationLoop
                plan={optimization}
                busy={busy}
                applied={optimizationApplied}
                onApply={applyOptimization}
              />
            )}
            {criticalMissing.length > 0 && (
              <div className="rounded border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
                <p className="flex items-center gap-2 font-medium">
                  <AlertTriangle size={16} /> 以下缺项会影响结论完整度
                </p>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-xs">
                  {criticalMissing.slice(0, 6).map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
                {criticalMissing.length > 6 && (
                  <details className="mt-2">
                    <summary className="cursor-pointer text-xs">展开其余 {criticalMissing.length - 6} 项</summary>
                    <ul className="mt-2 list-disc space-y-1 pl-5 text-xs">
                      {criticalMissing.slice(6).map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </details>
                )}
                <p className="mt-2 text-xs">这些缺项不会阻止查看当前结论，但当前等级不能当作完整核验。</p>
              </div>
            )}
            <div className="grid gap-3 lg:grid-cols-2">
              {dimensions.map(({ key }) => {
                const dimension = review.assessment.dimensions.find((item) => item.category === key);
                return dimension ? <DimensionCard key={key} dimension={dimension} /> : null;
              })}
            </div>
          </div>
        )}
      </div>
    </PageShell>
  );
};
