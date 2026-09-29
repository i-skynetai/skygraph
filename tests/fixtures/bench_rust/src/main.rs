mod repo;
mod service;

use crate::service::Service;

fn main() {
    let s = Service::new();
    s.handle("x");
}
