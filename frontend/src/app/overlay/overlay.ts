import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { OverlayService, OverlayData } from '../app-services/overlay-service';
import { ThemeService } from '../app-services/theme-service';


@Component({
  selector: 'app-overlay',
  imports: [FormsModule],
  templateUrl: './overlay.html',
  styleUrl: './overlay.css',
})
export class Overlay {
  constructor(
    private overlayService: OverlayService,
    private themeService: ThemeService
  ) {}

  closeOverlay() {
    this.overlayService.hideOverlay();
  }
}
