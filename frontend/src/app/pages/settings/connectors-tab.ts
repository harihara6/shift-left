import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { Api } from '../../core/api';
import { errorMessage } from '../../core/errors';
import { ConnectorDetail, ConnectorSummary, ConnectorTestResult } from '../../core/models';

@Component({
  selector: 'sl-connectors-tab',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  templateUrl: './connectors-tab.html',
  styleUrl: './settings.css',
})
export class ConnectorsTab {
  private readonly api = inject(Api);

  readonly connectors = signal<ConnectorSummary[]>([]);
  readonly selected = signal<ConnectorDetail | null>(null);
  readonly testResult = signal<ConnectorTestResult | null>(null);
  readonly notice = signal('');
  readonly rotating = signal<string | null>(null);
  readonly newSecret = signal('');

  /** Grouped by category, as the connector list in the design does. */
  readonly groups = computed(() => {
    const byCategory = new Map<string, ConnectorSummary[]>();
    for (const connector of this.connectors()) {
      const list = byCategory.get(connector.category) ?? [];
      list.push(connector);
      byCategory.set(connector.category, list);
    }
    return [...byCategory.entries()].map(([category, items]) => ({ category, items }));
  });

  constructor() {
    this.load();
  }

  private load(selectKey?: string): void {
    this.api.connectors().subscribe({
      next: (connectors) => {
        this.connectors.set(connectors);
        const next = selectKey ?? this.selected()?.key ?? connectors[0]?.key;
        if (next) this.select(next);
      },
      error: (err) => this.notice.set(errorMessage(err, 'The connector list could not be loaded.')),
    });
  }

  select(key: string): void {
    this.testResult.set(null);
    this.rotating.set(null);
    this.newSecret.set('');
    this.api.connector(key).subscribe({
      next: (detail) => this.selected.set(detail),
      error: (err) => this.notice.set(errorMessage(err, 'That connector could not be loaded.')),
    });
  }

  dotColor(connector: ConnectorSummary): string {
    if (connector.stale || connector.state === 'stale') return 'var(--watch)';
    if (connector.state === 'connected') return 'var(--good)';
    if (connector.state === 'error') return 'var(--poor)';
    return 'var(--neutral)';
  }

  chooseAuth(connector: ConnectorDetail, method: string): void {
    this.api.updateConnector(connector.key, { auth_method: method }).subscribe({
      next: (updated) => {
        this.selected.set(updated);
        this.notice.set(`Auth model set to ${method}.`);
      },
      error: (err) => this.notice.set(errorMessage(err, 'Could not change the auth model.')),
    });
  }

  saveField(connector: ConnectorDetail, key: string, value: string): void {
    this.api.updateConnector(connector.key, { config: { [key]: value } }).subscribe({
      next: (updated) => {
        this.selected.set(updated);
        this.notice.set('Configuration saved.');
      },
      error: (err) => {
        this.notice.set(errorMessage(err, 'Could not save the configuration.'));
        // Put the stored value back, so the field never shows an edit that was not saved.
        this.select(connector.key);
      },
    });
  }

  rotate(connector: ConnectorDetail, fieldKey: string): void {
    const value = this.newSecret();
    if (!value) return;
    // Cleared as soon as it is sent, whatever the outcome - the value is never held here.
    this.newSecret.set('');
    this.api.rotateSecret(connector.key, fieldKey, value).subscribe({
      next: () => {
        // The value goes to the vault. Nothing here keeps it, and nothing can read it back.
        this.rotating.set(null);
        this.notice.set('Credential rotated. The value went to the vault — this UI can never read it back.');
        this.select(connector.key);
      },
      error: (err) => this.notice.set(errorMessage(err, 'Could not rotate the credential.')),
    });
  }

  test(connector: ConnectorDetail): void {
    this.api.testConnector(connector.key).subscribe({
      next: (result) => this.testResult.set(result),
      error: (err) => this.notice.set(errorMessage(err, 'The connection test could not run.')),
    });
  }

  toggle(connector: ConnectorDetail): void {
    this.api.toggleConnector(connector.key).subscribe({
      next: () => {
        this.notice.set(
          connector.state === 'disabled'
            ? `${connector.name} enabled.`
            : `${connector.name} disabled. Widgets bound to it now render as gaps, not as zeros.`,
        );
        this.load(connector.key);
      },
      error: (err) => this.notice.set(errorMessage(err, `Could not change ${connector.name}.`)),
    });
  }
}
