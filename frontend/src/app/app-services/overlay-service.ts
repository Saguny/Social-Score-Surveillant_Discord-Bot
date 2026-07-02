import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

export type OverlayType =
    | "info"
    | "success"
    | "error"
    | "theme"
    | "link"
    | "debug";

export type OverlayState = {
    show: boolean;
    type: OverlayType;
    title: string;
    message?: string;
    link?: string;
}

@Injectable({ providedIn: 'root' })
export class OverlayService {
    private stateSubject = new BehaviorSubject<OverlayState>({show: false, type: "info", title: "Overlay"});
    public overlay$ = this.stateSubject.asObservable();

    showOverlay(type: OverlayType, title: string, message?: string, link?: string) {
        this.stateSubject.next({show: true, type, title, message, link});
    }

    hideOverlay() {
        const cur = this.stateSubject.value;
        this.stateSubject.next({ ...cur, show: false });
    }

    get current(): OverlayState {
        return this.stateSubject.value;
    }
}
