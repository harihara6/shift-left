import { HttpInterceptorFn } from '@angular/common/http';
import { Injectable, isDevMode, signal } from '@angular/core';

export interface Identity {
  email: string;
  groups: string[];
  label: string;
}

/**
 * Who is asking. Authorization is decided by the API, never here.
 *
 * In a production build the SSO proxy in front of the service authenticates the person and
 * sets the identity headers itself, so this app sends none and offers no way to choose. A
 * development build has no proxy: it names the caller from the switcher below, which makes the
 * project-scoped access model visible while developing.
 */
@Injectable({ providedIn: 'root' })
export class Session {
  /** Only a development build lets the caller choose who they are. */
  readonly canSwitch = isDevMode();

  readonly identities: Identity[] = [
    { email: 'h.nuti@backbase.com', groups: [], label: 'H. Nuti · platform admin' },
    {
      email: 'dev@backbase.com',
      groups: ['bb-eng-entitlements'],
      label: 'Engineer · contributor on ENT',
    },
    { email: 'qa@backbase.com', groups: ['bb-qa-shared'], label: 'QA · viewer on ENT' },
    { email: 'director@backbase.com', groups: ['bb-directors'], label: 'Director · viewer on PLT' },
  ];

  readonly current = signal<Identity>(this.identities[0]);

  use(email: string): void {
    if (!this.canSwitch) return;
    const found = this.identities.find((i) => i.email === email);
    if (found) this.current.set(found);
  }
}

export const sessionInterceptor: (session: Session) => HttpInterceptorFn =
  (session) => (req, next) => {
    // Behind the SSO proxy the identity headers are the proxy's to set, never the browser's.
    if (!session.canSwitch) return next(req);
    const identity = session.current();
    return next(
      req.clone({
        setHeaders: {
          'X-ShiftLeft-User': identity.email,
          'X-ShiftLeft-Groups': identity.groups.join(','),
        },
      }),
    );
  };
