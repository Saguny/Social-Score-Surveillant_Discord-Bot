import { Injectable } from '@angular/core';
import { BehaviorSubject, Subject } from 'rxjs';

export type OverlayType =
    | "info"
    | "success"
    | "error"
    | "theme"
    | "link"
    | "login"
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
        this.stateSubject.next({show: false, type: "info", title: "Overlay"});
    }

    getCurrentOverlay(): OverlayState {
        return this.stateSubject.value;
    }

}
