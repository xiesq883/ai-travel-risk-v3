import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { RiskExplanationChain } from './RiskExplanationChain';
import type { RiskExplanation } from '../../types/risk';

const chain: RiskExplanation = {
  data: [
    {
      field: 'walking_km',
      label: '步行',
      value: 12,
      unit: 'km',
      source_label: '手动录入',
      source_ids: ['source-1'],
      observed_at: '2026-10-16T04:00:00Z',
    },
  ],
  calculation: [{ expression: '12 ÷ 8 × 100', result: 150, unit: '%' }],
  rule: '>125% 为高',
  risk_level: 'high',
  explanation: '比上限多 4 km',
};

describe('RiskExplanationChain', () => {
  it('renders four ordered steps, arithmetic, provenance and action', () => {
    const html = renderToStaticMarkup(
      React.createElement(RiskExplanationChain, { explanation: chain, suggestion: '缩短步行' })
    );
    expect(html.indexOf('>数据<')).toBeLessThan(html.indexOf('>计算<'));
    expect(html.indexOf('>计算<')).toBeLessThan(html.indexOf('>风险<'));
    expect(html.indexOf('>风险<')).toBeLessThan(html.indexOf('>解释<'));
    for (const text of ['150', '高风险', 'source-1', '2026-10-16', '手动录入', '缩短步行'])
      expect(html).toContain(text);
  });

  it('distinguishes unknown, false and zero, and escapes user text', () => {
    const html = renderToStaticMarkup(
      React.createElement(RiskExplanationChain, {
        explanation: {
          ...chain,
          risk_level: 'unknown',
          data: [null, false, 0].map((value) => ({
            ...chain.data[0],
            value,
            unit: typeof value === 'number' ? 'km' : '',
            label: '<script>unsafe</script>',
          })),
        },
      })
    );
    expect(html).toContain('未知 / 未提供');
    expect(html).toContain('>否<');
    expect(html).toContain('>0 km<');
    expect(html).toContain('待核实');
    expect(html).toContain('&lt;script&gt;');
    expect(html).not.toContain('<script>');
  });
});
