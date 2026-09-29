<?php
use App\Svc\Repo;
use App\Svc\Service;

function run(): bool
{
    $s = new Service(new Repo());
    return $s->handle('x');
}
