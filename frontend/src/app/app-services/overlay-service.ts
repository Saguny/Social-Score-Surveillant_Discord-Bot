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

export type OverlayData = {
    show: boolean;
    type: OverlayType;
    title: string;
    message?: string;
    link?: string;
}

@Injectable()
export class OverlayService {
    private stateSubject = new BehaviorSubject<OverlayData>({show: false, type: "info", title: "Overlay"});
    public overlay$ = this.stateSubject.asObservable();

    showOverlay(type: OverlayType, title: string, message?: string, link?: string) {
        this.stateSubject.next({show: true, type, title, message, link});
    }

    hideOverlay() {
        this.stateSubject.next({show: false, type: "info", title: "Overlay"});
    }

    getCurrentOverlay(): OverlayData {
        return this.stateSubject.value;
    }

}
