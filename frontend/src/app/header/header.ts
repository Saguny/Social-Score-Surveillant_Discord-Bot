import { Component } from '@angular/core';
import { OverlayService } from '../app-services/overlay-service';
import { RouterLink } from '@angular/router';

@Component({
  selector: 'app-header',
  imports: [RouterLink],
  templateUrl: './header.html',
  styleUrl: './header.css',
})
export class Header {
  constructor(
    public overlay: OverlayService
  ) {}
}
