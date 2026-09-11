import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { FeatureRow } from '../../core/models';
import { RagBadge } from '../../ui/rag-badge';

/**
 * The evidence record for one feature.
 *
 * Everything here is the checklist and what it resolves to. The red block lists the literal
 * artifacts that are absent - there is no composite score anywhere on this panel, and nothing
 * an AI drafted counts until a named person has accepted it.
 */
@Component({
  selector: 'sl-evidence-panel',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RagBadge, DatePipe],
  host: { '(document:keydown.escape)': 'closed.emit()' },
  template: `
    <div class="scrim" (click)="closed.emit()"></div>
    <aside class="panel" role="dialog" aria-modal="true" [attr.aria-label]="'Evidence record for ' + feature().name">
      <header class="head">
        <div class="head-text">
          <div class="mono meta">{{ feature().key }} · {{ feature().tier }}</div>
          <h2>{{ feature().name }}</h2>
          <div class="head-status">
            <sl-rag [state]="feature().status" />
            <span class="at-gate">at {{ feature().gate }}</span>
          </div>
        </div>
        <button class="btn" (click)="closed.emit()">Close</button>
      </header>

      <div class="body">
        @if (feature().missing.length) {
          <section class="why-red">
            <h3>Why this is red — {{ feature().missing.length }} required artifacts absent</h3>
            <ul>
              @for (item of feature().missing; track item) { <li>{{ item }}</li> }
            </ul>
            <p class="why-note">
              No composite score is used. Restore the artifacts above and the status recomputes.
            </p>
          </section>
        } @else {
          <section class="why-clear">
            <h3>Why this is {{ feature().status.label }}</h3>
            <ul>
              @for (reason of feature().status.reasons; track reason) { <li>{{ reason }}</li> }
            </ul>
          </section>
        }

        <section class="block">
          <header class="block-head">
            <h3>Evidence checklist</h3>
            <span class="meta mono">
              Ready {{ feature().ready.label }} · Done {{ feature().done.label }}
            </span>
          </header>
          <table class="checklist">
            <caption class="sr-only">
              The eleven canonical artifacts for {{ feature().key }}, their state and their source record.
            </caption>
            <thead>
              <tr><th scope="col">Artifact</th><th scope="col">State</th><th scope="col">Source record</th></tr>
            </thead>
            <tbody>
              @for (artifact of feature().artifacts; track artifact.key) {
                <tr [class.not-due]="!artifact.counts_toward_gate">
                  <th scope="row">
                    <span class="artifact-name">{{ artifact.name }}</span>
                    <span class="artifact-meta">{{ artifact.accountable }} · {{ artifact.source }}</span>
                    @if (artifact.note) { <span class="artifact-note">{{ artifact.note }}</span> }
                    @if (artifact.status_only) {
                      <span class="artifact-meta">Presence and status only — content stays in the source system.</span>
                    }
                    @if (!artifact.counts_toward_gate) {
                      <span class="artifact-meta">
                        {{ artifact.status_label === 'Scoped out' ? 'Scoped out — outside both denominators' : 'Not due at ' + feature().gate }}
                      </span>
                    }
                  </th>
                  <td><sl-rag [state]="artifact.status" [showLabel]="false" /> <span class="state">{{ artifact.status_label }}</span></td>
                  <td class="drill-cell">
                    @if (artifact.drill; as drill) {
                      <a [href]="drill.url" target="_blank" rel="noopener">{{ drill.label }} ↗</a>
                    } @else {
                      <span class="no-drill">not linked</span>
                    }
                  </td>
                </tr>
              }
            </tbody>
          </table>
          <p class="gate-note">{{ feature().gate_note }}</p>
        </section>

        @if (feature().ai; as ai) {
          <section class="ai">
            <div class="ai-head">
              <span class="ai-tag">AI draft</span>
              <span class="meta">{{ ai.note }}</span>
            </div>
            <p class="ai-text">{{ ai.text }}</p>
            <p class="meta mono">Drawn from: {{ ai.drawn_from }}</p>
            <div class="ai-actions">
              @if (ai.accepted) {
                <span class="accepted mono">
                  Accepted by {{ ai.accepted_by }} · {{ ai.accepted_at | date: 'd MMM y, HH:mm' }}
                </span>
              } @else {
                <button class="btn btn-primary" (click)="acceptDraft.emit(feature().key)">
                  Accept as evidence
                </button>
                <span class="meta">Acceptance is recorded against your name and audited.</span>
              }
            </div>
          </section>
        }

        <section class="block">
          <h3>Owner &amp; next action</h3>
          <div class="next">
            <p>{{ feature().next_action }}</p>
            <p class="meta mono">{{ feature().owner }} · action record open {{ feature().action_age }}</p>
          </div>
        </section>

        <section class="block">
          <h3>Linked flow record</h3>
          <button class="flow" (click)="openFlow.emit()">
            <span>
              <span class="flow-title">Delivery Control · same team, same window</span>
              <span class="meta">Flow telemetry does not change any status above.</span>
            </span>
            <span class="arrow" aria-hidden="true">→</span>
          </button>
        </section>
      </div>
    </aside>
  `,
  styles: [
    `
      .scrim { position: fixed; inset: 0; background: rgba(18, 19, 22, 0.42); z-index: 40; }
      .panel {
        position: fixed; top: 0; right: 0; bottom: 0; width: 660px; max-width: 94vw;
        background: var(--surface); border-left: 1px solid var(--border); z-index: 41;
        box-shadow: -24px 0 60px rgba(18, 19, 22, 0.14);
        display: flex; flex-direction: column; overflow: hidden;
      }
      .head {
        flex: 0 0 auto; padding: 20px 24px 16px; border-bottom: 1px solid var(--border-soft);
        display: flex; align-items: flex-start; justify-content: space-between; gap: 16px;
      }
      .head-text { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
      h2 { margin: 0; font-size: 18px; font-weight: 600; letter-spacing: -0.015em; line-height: 1.3; }
      .head-status { display: flex; align-items: center; gap: 8px; font-size: 12.5px; }
      .at-gate { color: var(--muted); }
      /* Scrollable flex column: children must not compress instead of the container scrolling. */
      .body { flex: 1; overflow-y: auto; padding: 18px 24px 40px; display: flex; flex-direction: column; gap: 20px; }
      .body > * { flex: 0 0 auto; }
      h3 { margin: 0; font-size: 13px; font-weight: 600; }

      .why-red, .why-clear {
        border-radius: 10px; padding: 14px 16px; display: flex; flex-direction: column; gap: 8px;
      }
      .why-red { background: var(--poor-bg); border: 1px solid #f1cfc9; color: #8f241c; }
      .why-clear { background: var(--surface-sunken); border: 1px solid var(--border-soft); color: var(--ink-2); }
      .why-red h3 { color: #8f241c; }
      .why-red ul, .why-clear ul { margin: 0; padding-left: 18px; font-size: 12.5px; line-height: 1.55; }
      .why-note { margin: 0; font-size: 11.5px; color: #a85a50; line-height: 1.5; }

      .block { display: flex; flex-direction: column; gap: 10px; }
      .block-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }

      .checklist { width: 100%; border-collapse: collapse; border: 1px solid var(--border-soft); border-radius: 10px; }
      .checklist thead th {
        text-align: left; font-size: 10.5px; letter-spacing: 0.06em; text-transform: uppercase;
        color: var(--faint); font-weight: 400; padding: 9px 14px; background: var(--surface-sunken);
        border-bottom: 1px solid var(--border-soft);
      }
      .checklist tbody th, .checklist td {
        text-align: left; font-weight: 400; padding: 11px 14px;
        border-bottom: 1px solid var(--border-softer); vertical-align: top;
      }
      .checklist tbody tr:last-child th, .checklist tbody tr:last-child td { border-bottom: none; }
      .not-due { background: var(--surface-sunken); }
      .artifact-name { display: block; font-size: 12.5px; color: var(--ink); }
      .artifact-meta { display: block; font-size: 11px; color: var(--faint); margin-top: 3px; line-height: 1.45; }
      .artifact-note { display: block; font-size: 11.5px; color: var(--watch); margin-top: 3px; line-height: 1.45; }
      .state { font-size: 11.5px; color: var(--ink-2); }
      .drill-cell { text-align: right; font-size: 11.5px; white-space: nowrap; }
      .no-drill { color: #c7c6c1; }
      .gate-note { margin: 0; font-size: 11.5px; color: var(--faint); line-height: 1.55; }

      .ai {
        border: 1px solid var(--accent-border); background: #f7f8ff; border-radius: 10px;
        padding: 14px 16px; display: flex; flex-direction: column; gap: 10px;
      }
      .ai-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
      .ai-tag {
        font-size: 10px; letter-spacing: 0.07em; text-transform: uppercase; color: var(--accent);
        background: #e4e9ff; border-radius: 5px; padding: 2px 7px; font-weight: 600;
      }
      .ai-text { margin: 0; font-size: 12.5px; color: var(--ink-2); line-height: 1.55; }
      .ai-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
      .accepted { font-size: 11.5px; color: var(--good); }

      .next { border: 1px solid var(--border-soft); border-radius: 10px; padding: 14px 16px; }
      .next p { margin: 0 0 6px; font-size: 12.5px; color: var(--ink); line-height: 1.55; }
      .next p:last-child { margin: 0; }

      .flow {
        display: flex; align-items: center; justify-content: space-between; gap: 12px;
        text-align: left; width: 100%; background: var(--surface); border: 1px solid var(--border-soft);
        border-radius: 10px; padding: 14px 16px; cursor: pointer; font-family: inherit;
      }
      .flow:hover { border-color: var(--accent); }
      .flow-title { display: block; font-size: 12.5px; color: var(--ink); margin-bottom: 3px; }
      .arrow { color: var(--accent); font-size: 15px; }
      .meta { font-size: 11.5px; color: var(--faint); line-height: 1.5; }

      @media (max-width: 720px) {
        .checklist thead { display: none; }
        .checklist tbody th, .checklist td { display: block; border-bottom: none; padding: 6px 14px; }
        .checklist tbody tr { display: block; border-bottom: 1px solid var(--border-softer); padding: 8px 0; }
        .drill-cell { text-align: left; }
      }
    `,
  ],
})
export class EvidencePanel {
  readonly feature = input.required<FeatureRow>();
  readonly closed = output<void>();
  readonly acceptDraft = output<string>();
  readonly openFlow = output<void>();
}
