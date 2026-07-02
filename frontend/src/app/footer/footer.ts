import { Component } from '@angular/core';
import { OverlayService } from '../app-services/overlay-service';
import { RouterLink } from '@angular/router';

@Component({
  selector: 'app-footer',
  imports: [RouterLink],
  templateUrl: './footer.html',
  styleUrl: './footer.css',
})
export class Footer {
  constructor(
    public overlay: OverlayService
  ) {}
}
