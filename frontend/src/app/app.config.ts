import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { ApplicationConfig, inject, provideBrowserGlobalErrorListeners } from '@angular/core';

import { Session, sessionInterceptor } from './core/session';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideHttpClient(
      // Attaches the caller's identity. Authorization itself is always decided server-side.
      withInterceptors([(req, next) => sessionInterceptor(inject(Session))(req, next)]),
    ),
  ],
};
