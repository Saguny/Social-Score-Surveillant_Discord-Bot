import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { OverlayService } from '../app-services/overlay-service';

@Component({
  selector: 'app-overlay',
  imports: [CommonModule],
  templateUrl: './overlay.html',
  styleUrl: './overlay.css',
})
export class Overlay {
  public overlay = inject(OverlayService);
  
  overlayState$ = this.overlay.overlay$;

  close() {
    this.overlay.hideOverlay();
  }
}