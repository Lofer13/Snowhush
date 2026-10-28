#[cfg(windows)]
pub mod card;
pub mod geometry;
#[cfg(windows)]
pub mod install;
pub mod layer;
pub mod remote;
pub mod simulation;
pub mod version;

#[cfg(test)]
mod tests;
